#!/usr/bin/env python3
"""
Charlie Walking donut claimer.

Claims donut rewards (daily, 5k/10k step milestones, optionally ad-bonus)
directly against the Charlie Walking API using a session obtained via
Google OAuth replay.

Usage:
  python3 charlie_claimer.py --status          # show balance + events
  python3 charlie_claimer.py --once            # single claim pass
  python3 charlie_claimer.py --loop            # run forever (default interval: 60 min)

Config (charlie_claimer.json, same dir):
{
  "google": {
    "client_id": "...apps.googleusercontent.com",
    "client_secret": "GOCSPX-...",
    "refresh_token": "<Google refresh token>"
  },
  "charlie": {
    "base_url": "https://charlieapp-prod.nombs.site/api/v3",
    "access_token": "<Charlie JWT>",
    "refresh_token": "<Charlie JWT refresh>"
  },
  "events": {"claim_ids": [1, 6, 7], "interval_minutes": 60}
}
Event IDs: 1=daily, 6=5k steps, 7=10k steps, 2=ad bonus (opt-in).
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

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "charlie-replay.json")
UA = "charlie-flutter/2.18.16"


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


def google_refresh(cfg):
    """Exchange the Google refresh token for a fresh access token."""
    g = cfg["google"]
    body = urllib.parse.urlencode({
        "client_id": g["client_id"],
        "client_secret": g["client_secret"],
        "refresh_token": g["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    status, text = http("POST", "https://oauth2.googleapis.com/token",
                        {"Content-Type": "application/x-www-form-urlencoded"}, body)
    if status != 200:
        raise RuntimeError(f"Google token refresh failed: {status} {text[:300]}")
    data = json.loads(text)
    g["access_token"] = data["access_token"]
    if "refresh_token" in data:  # rotation
        g["refresh_token"] = data["refresh_token"]
    g["expires_at"] = time.time() + data.get("expires_in", 3600)
    log("Google access token refreshed.")
    return data["access_token"]


def charlie_login(cfg):
    """Replay the app's Google login to get a fresh Charlie JWT pair."""
    base = cfg["charlie"]["base_url"]
    g_access = cfg["google"].get("access_token")
    if not g_access or time.time() > cfg["google"].get("expires_at", 0) - 60:
        g_access = google_refresh(cfg)
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


def api_post(cfg, path, payload):
    c = cfg["charlie"]
    body = json.dumps(payload)
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
    claimed_any = False
    for ev in get_events(cfg):
        if ev["id"] in want and ev.get("isClaimable"):
            claimed_any = claim_event(cfg, ev) or claimed_any
    return claimed_any


def status_pass(cfg):
    balance = api_get(cfg, "/donut/balance")
    events = get_events(cfg)
    log(f"balance: {balance['balance']} donuts")
    for e in events:
        log(f"  id={e['id']} {e['type']:<14} {e['titleEn']:<20} "
            f"claimable={e['isClaimable']} ({e['claimedCount']}/{e['claimableCount']}) "
            f"threshold={e.get('rewardThreshold')}")


def run(cfg, loop, interval_min):
    while True:
        try:
            ensure_auth(cfg)
            claim_pass(cfg)
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
