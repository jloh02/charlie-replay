#!/usr/bin/env python3
"""
One-time bootstrap for charlie-replay.

Usage:
  python3 bootstrap.py <client_id> <client_secret>

Runs a local Google OAuth PKCE flow (open the printed URL in your browser,
select the Google account your Charlie account uses), then performs the
initial Charlie login and writes ./charlie-replay.json.
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


def oauth_flow(client_id, client_secret):
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
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
    print("OPEN THIS URL IN YOUR BROWSER (pick the Google account your")
    print("Charlie account uses):")
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


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    client_id, client_secret = sys.argv[1], sys.argv[2]

    tokens = oauth_flow(client_id, client_secret)
    log("Google tokens received (email scope granted).")

    charlie = charlie_login(tokens["access_token"])
    log("Charlie session established.")

    status, text = http("GET", BASE_URL + "/donut/balance",
                        {"Authorization": "Bearer " + charlie["accessToken"], "User-Agent": UA})
    log(f"donut balance: {json.loads(text)['balance']}")

    cfg = {
        "google": {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": tokens["refresh_token"],
        },
        "charlie": {
            "base_url": BASE_URL,
            "access_token": charlie["accessToken"],
            "refresh_token": charlie["refreshToken"],
        },
        "events": {"claim_ids": [1, 6, 7], "interval_minutes": 60},
    }
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(CONFIG_PATH, 0o600)
    log(f"wrote {CONFIG_PATH} (chmod 600). You can now run: docker compose up -d")


if __name__ == "__main__":
    main()
