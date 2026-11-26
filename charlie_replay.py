#!/usr/bin/env python3
"""
Charlie Walking session-replay claimer.

Claims donut rewards (daily, 5k/10k step milestones, optionally ad-bonus) and
completes eligible missions (boosters, monthly honorary, milestones) directly
against the Charlie Walking API, using a session obtained via Google OAuth
replay. The session renews itself (Google refresh token -> Charlie JWT).

Also pushes daily step totals to the server (POST /walk/bulk) from the
Google Health store (the cloud store the Google Health app on your phone
syncs — phone pedometer, Health Connect and device data), so step
milestones become claimable without the Charlie app on the phone having to
sync anything. The deprecated Google Fit REST API is NOT used.

Usage:
  python3 charlie_replay.py --status          # show balance + events + missions
  python3 charlie_replay.py --once            # single claim pass
  python3 charlie_replay.py --loop            # run forever (default interval: 60 min)
  python3 charlie_replay.py --relogin         # force a fresh Charlie JWT

Config (charlie-replay.json, same dir):
{
  "google":  { "client_id": "...", "client_secret": "...", "refresh_token": "..." },
  "charlie": { "base_url": "...", "access_token": "...", "refresh_token": "..." },
  "events":  { "claim_ids": [1, 6, 7], "interval_minutes": 60 },
  "missions": { "auto_complete": true },
  "steps":   { "enabled": true, "lookback_days": 7,
               "health": { "enabled": true, "client_id": "...",
                           "client_secret": "...", "refresh_token": "..." } }
}
Event IDs: 1=daily, 6=5k steps, 7=10k steps, 2=ad bonus (opt-in).
Missions: any active mission with progress.isCompletable is completed.
Steps: the Health grant (steps.health) is its own OAuth grant — it may be a
*different* Google account than the Charlie login one — with the
googlehealth.activity_and_fitness.readonly scope. Obtain it with
`bootstrap.py --health` (pick the account that has the
Google Health app on the phone).
"""
import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "charlie-replay.json")
UA = "charlie-flutter/2.18.16"
_steps_off_logged = False  # announce "no Health grant" once per process


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def http(method, url, headers=None, data=None, timeout=30):
    body = data.encode() if isinstance(data, str) else data
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def jwt_exp(token):
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p)).get("exp", 0)
    except Exception:
        return 0


def google_refresh(creds):
    """Exchange a Google refresh token for a fresh access token.

    `creds` is a config dict holding client_id/client_secret/refresh_token;
    access_token/expires_at are updated in place (and saved by the caller).
    Works for any grant — the Charlie login account or the separate Health
    account.
    """
    body = urllib.parse.urlencode({
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    status, text = http("POST", "https://oauth2.googleapis.com/token",
                        {"Content-Type": "application/x-www-form-urlencoded"}, body)
    if status != 200:
        raise RuntimeError(f"Google token refresh failed: {status} {text[:300]}")
    data = json.loads(text)
    creds["access_token"] = data["access_token"]
    if "refresh_token" in data:  # rotation
        creds["refresh_token"] = data["refresh_token"]
    creds["expires_at"] = time.time() + data.get("expires_in", 3600)
    log("Google access token refreshed.")
    return data["access_token"]


def charlie_login(cfg):
    """Replay the app's Google login to get a fresh Charlie JWT pair."""
    base = cfg["charlie"]["base_url"]
    g = cfg["google"]
    g_access = g.get("access_token")
    if not g_access or time.time() > g.get("expires_at", 0) - 60:
        g_access = google_refresh(g)
    body = json.dumps({"accessToken": g_access, "authorizationCode": "n/a"})
    status, text = http("POST", base + "/auth/login/google",
                        {"Content-Type": "application/json", "User-Agent": UA}, body)
    if status not in (200, 201):
        raise RuntimeError(f"Charlie login failed: {status} {text[:300]}")
    data = json.loads(text)
    cfg["charlie"]["access_token"] = data["accessToken"]
    cfg["charlie"]["refresh_token"] = data["refreshToken"]
    log("Charlie JWT pair renewed (access exp: %s)."
        % time.strftime('%Y-%m-%d %H:%M', time.gmtime(jwt_exp(data["accessToken"]))))


def ensure_auth(cfg):
    c = cfg["charlie"]
    if jwt_exp(c.get("access_token", "")) < time.time() + 3600:
        charlie_login(cfg)
        save_config(cfg)


def api_get(cfg, path):
    c = cfg["charlie"]
    status, text = http("GET", c["base_url"] + path,
                        {"Authorization": "Bearer " + c["access_token"], "User-Agent": UA})
    if status == 401:
        ensure_auth(cfg)
        status, text = http("GET", c["base_url"] + path,
                            {"Authorization": "Bearer " + c["access_token"], "User-Agent": UA})
    if status != 200:
        raise RuntimeError(f"GET {path} failed: {status} {text[:300]}")
    return json.loads(text)


def api_post(cfg, path, payload=None):
    c = cfg["charlie"]
    body = json.dumps(payload) if payload is not None else None
    status, text = http("POST", c["base_url"] + path,
                        {"Authorization": "Bearer " + c["access_token"],
                         "Content-Type": "application/json", "User-Agent": UA}, body)
    if status == 401:
        ensure_auth(cfg)
        status, text = http("POST", c["base_url"] + path,
                            {"Authorization": "Bearer " + c["access_token"],
                             "Content-Type": "application/json", "User-Agent": UA}, body)
    return status, json.loads(text or "{}")


def get_events(cfg):
    return api_get(cfg, "/donut/events")


def get_active_missions(cfg):
    return api_get(cfg, "/mission/v2/active")


def complete_mission(cfg, mission):
    status, data = api_post(cfg, f"/mission/{mission['id']}/complete")
    if status in (200, 201):
        r = data.get("rewarded", {})
        if r.get("donuts"):
            reward = f"+{r['donuts']} donut(s)"
        elif r.get("badge"):
            reward = f"badge: {r['badge'].get('nameEn')}"
        elif r.get("item"):
            reward = f"item: {r['item'].get('nameEn')}"
        else:
            reward = json.dumps(r)[:80]
        log(f"MISSION COMPLETE id={mission['id']} :: {mission.get('displayTitleEn')} -> {reward}")
        return True
    if data.get("message") == "ALREADY_COMPLETED_MISSION":
        return False
    log(f"complete mission id={mission['id']} failed: {status} {json.dumps(data)[:200]}")
    return False


def mission_pass(cfg):
    if not cfg.get("missions", {}).get("auto_complete", True):
        return 0
    done = 0
    for m in get_active_missions(cfg):
        if m.get("progress", {}).get("isCompletable"):
            if complete_mission(cfg, m):
                done += 1
    return done


def claim_event(cfg, event):
    status, data = api_post(cfg, "/donut/events", {"eventId": event["id"]})
    if status in (200, 201) and data.get("success"):
        log(f"CLAIMED {event['type']:<14} id={event['id']} (+{data['data']['donuts']} donut(s), "
            f"balance now {data['data']['balance']}) :: {event['titleEn']}")
        return True
    log(f"claim id={event['id']} failed: {status} {json.dumps(data)[:200]}")
    return False


def claim_pass(cfg):
    want = set(cfg.get("events", {}).get("claim_ids", [1, 6, 7]))
    claimed = 0
    for ev in get_events(cfg):
        if ev["id"] in want and ev.get("isClaimable"):
            if claim_event(cfg, ev):
                claimed += 1
    claimed += mission_pass(cfg)
    return claimed


def status_pass(cfg):
    balance = api_get(cfg, "/donut/balance")
    events = get_events(cfg)
    log(f"balance: {balance['balance']} donuts")
    for e in events:
        log(f"  id={e['id']} {e['type']:<14} {e['titleEn']:<20} "
            f"claimable={e['isClaimable']} ({e['claimedCount']}/{e['claimableCount']}) "
            f"threshold={e.get('rewardThreshold')}")
    for m in get_active_missions(cfg):
        p = m.get("progress", {})
        log(f"  mission id={m['id']} {m.get('displayTitleEn',''):<28} "
            f"state={p.get('state')} completable={p.get('isCompletable')} "
            f"({p.get('currentProgressValue')}/{m.get('threshold')}) reward={m.get('reward')}")


# ---------------------------------------------------------------- step sync

# Account timezone per /walk/today ("timezone": "Asia/Singapore"). Fixed
# UTC+8, no DST — a constant offset is exact, no tz database needed.
SGT = timezone(timedelta(hours=8))
HEALTH_ROLLUP_URL = ("https://health.googleapis.com/v4/users/me/dataTypes/"
                     "steps/dataPoints:dailyRollUp")


def sgt_today():
    return datetime.now(SGT).date()


def _civil(date):
    return {"date": {"year": date.year, "month": date.month, "day": date.day}}


def health_daily_rollup(cfg, start_day, end_day_excl):
    """Reconciled per-day step totals from the Google Health store (the
    cloud store the Google Health app on the phone syncs — phone pedometer,
    Health Connect and device data). Uses the separate health-account grant
    stored in steps.health (its own Google account, independent of the
    Charlie login account).

    One dailyRollUp call for the whole civil-day range [start_day,
    end_day_excl). Returns {iso_date: steps} for days that have step data;
    a day absent from the dict means the store has no steps for it (app
    wasn't recording), which is different from a real 0-step day.
    """
    hc = cfg.get("steps", {}).get("health") or {}
    if not hc.get("client_id") or not hc.get("refresh_token"):
        raise RuntimeError("Health grant not configured — run: "
                           "python3 bootstrap.py --health")
    if not hc.get("access_token") or time.time() > hc.get("expires_at", 0) - 60:
        hc_access = google_refresh(hc)
    else:
        hc_access = hc["access_token"]
    payload = {
        "range": {"start": _civil(start_day), "end": _civil(end_day_excl)},
        "windowSizeDays": 1,
    }
    headers = {"Authorization": "Bearer " + hc_access,
               "Content-Type": "application/json", "User-Agent": "charlie-replay/1.0"}
    status, text = http("POST", HEALTH_ROLLUP_URL, headers, json.dumps(payload))
    if status == 401:  # stale access token: refresh once and retry
        hc_access = google_refresh(hc)
        headers["Authorization"] = "Bearer " + hc_access
        status, text = http("POST", HEALTH_ROLLUP_URL, headers, json.dumps(payload))
    if status != 200:
        if status == 403 and "insufficient" in text.lower():
            raise RuntimeError("Health scope missing — run: "
                               "python3 bootstrap.py --health")
        raise RuntimeError(f"Health dailyRollUp failed: {status} {text[:300]}")
    out = {}
    for rp in json.loads(text).get("rollupDataPoints", []):
        if "steps" not in rp:
            continue  # day with no step data (not even an explicit 0)
        start = rp["civilStartTime"]["date"]
        iso = f"{start['year']:04d}-{start['month']:02d}-{start['day']:02d}"
        out[iso] = int(rp["steps"]["countSum"])
    return out


def steps_pass(cfg):
    """Push per-day step totals (Google Health store) to /walk/bulk.

    Guarded upsert: a day is only pushed when the Health store has data
    for it and the total is *higher* than the value the server already
    holds, so under-counted days get backfilled and today keeps
    refreshing, but a recorded total is never lowered. Days whose server
    value can't be read (previous month) are skipped.
    """
    global _steps_off_logged
    st = cfg.setdefault("steps", {})
    if not st.get("enabled", True):
        return
    health_cfg = st.get("health") or {}
    if not health_cfg.get("enabled", True):
        return
    # Step sync is opt-in via the --health bootstrap, which writes the grant
    # (incl. the refresh token) into steps.health. Without a grant this pass
    # never runs — announced once, then silent.
    if not health_cfg.get("refresh_token"):
        if not _steps_off_logged:
            _steps_off_logged = True
            log("steps: no Health grant in config — step sync off "
                "(run `python3 bootstrap.py --health` to enable)")
        return
    lookback = st.get("lookback_days", 7)
    today = sgt_today()

    try:
        roll = health_daily_rollup(cfg, today - timedelta(days=lookback),
                                   today + timedelta(days=1))
    except RuntimeError as e:
        log("steps: " + str(e))
        return

    server = {}
    try:
        cal = api_get(cfg, "/walk/calendar/month")
        for w in cal.get("walks", []):
            server[w["localDateString"]] = w["steps"]
    except Exception as e:
        log(f"steps: server calendar unreadable ({e})")
    try:
        t = api_get(cfg, "/walk/today")
        server[t["localDateString"]] = t["steps"]
    except Exception as e:
        log(f"steps: /walk/today unreadable ({e})")

    pushes = []
    for i in range(lookback, -1, -1):
        day = today - timedelta(days=i)
        ds = day.isoformat()

        if ds not in roll:
            log(f"steps: {ds} no Health data — skipped")
            continue
        health_v = roll[ds]
        if ds not in server:
            if day != today:
                log(f"steps: {ds} server value not verifiable (previous month) — skipped")
                continue
            log(f"steps: {ds} push {health_v}")
            pushes.append({"date": ds, "steps": health_v})
        elif health_v <= server[ds]:
            log(f"steps: {ds} {health_v} <= server {server[ds]} — not raised")
        else:
            log(f"steps: {ds} {server[ds]} -> {health_v}")
            pushes.append({"date": ds, "steps": health_v})

    # persist any refreshed Health tokens (incl. rotation) for the next run
    save_config(cfg)
    if pushes:
        status, data = api_post(cfg, "/walk/bulk", pushes)
        if status in (200, 201):
            log(f"steps: pushed {len(pushes)} day(s) to /walk/bulk")
        else:
            log(f"steps: /walk/bulk failed: {status} {json.dumps(data)[:300]}")


def run(cfg, loop, interval_min):
    while True:
        try:
            ensure_auth(cfg)
            if cfg.get("steps", {}).get("enabled", True):
                try:
                    steps_pass(cfg)
                except Exception as e:
                    log(f"steps pass failed: {e}")
            claimed = claim_pass(cfg)
            balance = api_get(cfg, "/donut/balance")["balance"]
            log(f"pass ok: claimed {claimed} reward(s), balance={balance}")
        except Exception as e:
            log(f"pass failed: {e}")
        if not loop:
            break
        time.sleep(interval_min * 60)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true", help="show balance + events and exit")
    ap.add_argument("--once", action="store_true", help="single claim pass and exit")
    ap.add_argument("--loop", action="store_true", help="run claim loop forever")
    ap.add_argument("--relogin", action="store_true", help="force Charlie re-login and exit")
    args = ap.parse_args()

    cfg = load_config()
    if args.relogin:
        ensure_auth(cfg)
        charlie_login(cfg)
        save_config(cfg)
        return
    if args.status:
        ensure_auth(cfg)
        status_pass(cfg)
        return
    interval = cfg.get("events", {}).get("interval_minutes", 60)
    if args.loop:
        log(f"starting claim loop (every {interval} min), claim ids: "
            f"{cfg.get('events', {}).get('claim_ids', [1, 6, 7])}")
    run(cfg, args.loop or not args.once, interval)


if __name__ == "__main__":
    main()
