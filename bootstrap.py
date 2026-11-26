#!/usr/bin/env python3
"""
One-time bootstrap for charlie-replay.

Usage:
  python3 bootstrap.py [<client_id> <client_secret>] [--health]
      The credentials are only needed for the FIRST bootstrap (there is no
      file to read them from yet); every later run reads them from
      charlie-replay.json, so plain invocations are:
        python3 bootstrap.py            fresh/re-run the Charlie login grant
        python3 bootstrap.py --health   add/re-run the Health API grant

  --health:
      Add the Google Health API grant (googlehealth.activity_and_fitness.
      readonly scope), so the daemon can pull phone step counts from the
      Google Health store. Pick the Google account that has the Google
      Health app on the phone (the app that was Google Fit) — it may be a
      *different* account than the Charlie login one; the grant is stored
      separately in steps.health and never touches the Charlie login
      tokens.

Run the local Google OAuth PKCE flow (open the printed URL in your browser,
select the Google account your Charlie account uses), then performs the
initial Charlie login and writes ./charlie-replay.json.

NOTE: while the OAuth client is in "Testing" status, Google refresh tokens
expire 7 days after consent. For a long-running daemon, set the client to
"In production" (unverified is fine) in console.cloud.google.com.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import socketserver
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "charlie-replay.json")
REDIRECT_URI = "http://127.0.0.1:8765/callback"
BASE_URL = "https://charlieapp-prod.nombs.site/api/v3"
UA = "charlie-flutter/2.18.16"


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def http(method, url, headers=None, data=None, timeout=30):
    body = data.encode() if isinstance(data, str) else data
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def oauth_flow(client_id, client_secret, scope, hint):
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # Always force the account chooser: the browser's "default" account
        # is the most recently used one, which we can't (and don't want to)
        # rely on when the two grants may belong to different accounts.
        "prompt": "select_account",
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)

    captured = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.urlparse(self.path)
            p = urllib.parse.parse_qs(q.query)
            if q.path == "/callback" and "code" in p:
                captured["code"] = p["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h2>Code captured. You can close this tab.</h2>")
            else:
                self.send_response(400)
                self.end_headers()

        def log_message(self, *a):
            pass

    print()
    print("OPEN THIS URL IN YOUR BROWSER:")
    print(f"  {hint}")
    print()
    print(auth_url)
    print()
    log("waiting for the redirect on 127.0.0.1:8765 ...")

    with socketserver.TCPServer(("127.0.0.1", 8765), Handler) as httpd:
        httpd.timeout = 600
        httpd.handle_request()

    if "code" not in captured:
        sys.exit("OAuth flow failed (no code captured).")

    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": captured["code"],
        "grant_type": "authorization_code",
        "code_verifier": verifier,
        "redirect_uri": REDIRECT_URI,
    }).encode()
    status, text = http("POST", "https://oauth2.googleapis.com/token",
                        {"Content-Type": "application/x-www-form-urlencoded"}, body)
    if status != 200:
        sys.exit(f"token exchange failed: {status} {text[:300]}")
    return json.loads(text)


def charlie_login(g_access):
    status, text = http("POST", BASE_URL + "/auth/login/google",
                        {"Content-Type": "application/json", "User-Agent": UA},
                        json.dumps({"accessToken": g_access, "authorizationCode": "n/a"}))
    if status not in (200, 201):
        sys.exit(f"Charlie login failed: {status} {text[:300]}")
    return json.loads(text)


def whoami(access_token):
    """Resolve the Google account behind an access token (for verification)."""
    status, text = http("GET", "https://www.googleapis.com/oauth2/v3/userinfo",
                        {"Authorization": "Bearer " + access_token})
    if status == 200:
        return json.loads(text).get("email")
    log(f"userinfo failed: {status} {text[:200]}")
    return None


def pick_refresh(tokens, fallback):
    """Return the refresh token from a token response.

    On a re-run Google often omits it (the account already consented to
    the same scopes — the previously issued token stays valid); in that
    case the stored one is reused.
    """
    rt = tokens.get("refresh_token")
    if rt:
        return rt
    if fallback:
        log("Google returned no new refresh token (account already "
            "consented) — reusing the stored one.")
        return fallback
    sys.exit("Google returned no refresh token and none is stored. Sign "
             "out of the account in the browser (or use a private window) "
             "and re-run the bootstrap.")


def main():
    health = "--health" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--health"]
    client_id = client_secret = None
    if len(args) == 2:
        client_id, client_secret = args
    elif len(args) == 0:
        # no args: reuse the credentials stored by the first bootstrap
        if os.path.exists(CONFIG_PATH):
            g0 = json.load(open(CONFIG_PATH)).get("google", {})
            client_id, client_secret = g0.get("client_id"), g0.get("client_secret")
        if not client_id or not client_secret:
            sys.exit("No client credentials: the first bootstrap needs them "
                     "as arguments (python3 bootstrap.py <client_id> "
                     "<client_secret>); later runs read them from "
                     "charlie-replay.json.")
    else:
        sys.exit(__doc__)

    scope = "openid email profile"
    if health:
        scope += " https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly"
        if not os.path.exists(CONFIG_PATH):
            sys.exit("No existing config — run a plain bootstrap first.")

    if health:
        hint = ("pick the account that has the GOOGLE HEALTH app on the phone "
                "(the app that was Google Fit) — NOT the Charlie login account")
    else:
        hint = "pick the Google account your Charlie account uses"
    tokens = oauth_flow(client_id, client_secret, scope, hint)
    log(f"Google tokens received ({scope}).")

    if health:
        cfg = json.load(open(CONFIG_PATH))
        health_email = whoami(tokens["access_token"])
        log(f"Health grant account: {health_email}")
        charlie_email = None
        g = cfg.get("google", {})
        if health_email and g.get("refresh_token"):
            try:
                if not g.get("access_token") or time.time() > g.get("expires_at", 0) - 60:
                    from charlie_replay import google_refresh
                    google_refresh(g)
                charlie_email = whoami(g["access_token"])
            except Exception as e:
                log(f"could not verify Charlie login account: {e}")
            if charlie_email == health_email:
                log("WARNING: Health grant uses the SAME account as the Charlie login.")
                log("If your phone's Health app is signed into a different account,")
                log("re-run with --health and pick that one in the account chooser.")
        st = cfg.setdefault("steps", {})
        st["health"] = {
            "enabled": True,
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": pick_refresh(
                tokens, (cfg.get("steps", {}).get("health") or {}).get("refresh_token")),
        }
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
        os.chmod(CONFIG_PATH, 0o600)
        log("Health grant saved to steps.health (separate from the Charlie")
        log("login account). The claimer will use it for the daily step sync.")
        return

    charlie = charlie_login(tokens["access_token"])
    log("Charlie session established.")

    status, text = http("GET", BASE_URL + "/donut/balance",
                        {"Authorization": "Bearer " + charlie["accessToken"], "User-Agent": UA})
    log(f"donut balance: {json.loads(text)['balance']}")

    # On a re-run, keep the existing sections (steps, missions, ...); only
    # refresh the grants.
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            cfg = json.load(open(CONFIG_PATH))
        except Exception:
            log("existing config unreadable — starting fresh")
            cfg = {}
    prev_rt = cfg.get("google", {}).get("refresh_token")
    cfg["google"] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": pick_refresh(tokens, prev_rt),
    }
    cfg["charlie"] = {
        "base_url": BASE_URL,
        "access_token": charlie["accessToken"],
        "refresh_token": charlie["refreshToken"],
    }
    cfg.setdefault("events", {"claim_ids": [1, 6, 7], "interval_minutes": 60})
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(CONFIG_PATH, 0o600)
    log(f"wrote {CONFIG_PATH} (chmod 600). You can now run: docker compose up -d")


if __name__ == "__main__":
    main()
