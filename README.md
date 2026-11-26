# charlie-replay

Server-side donut claimer for the [Charlie Walking](https://play.google.com/store/apps/details?id=com.charlie.walking) app.
Claims the daily / 5k / 10k-step donut rewards against the app's private API — no app interaction, no ads.

> ⚠️ Unofficial client on a private API. The app has no published terms of service
> (its only legal document is a privacy policy that doesn't restrict API use), but
> account restriction/termination remains the developer's unilateral right if they
> notice. Use at your own risk.

## How it works

- **Session**: Google OAuth replay → `POST /api/v3/auth/login/google` → Charlie JWT
  (access ~90 d, refresh ~1 y; the daemon re-logs in before they run out).
  Chain: Google refresh token → Google access token (1 h) → Charlie JWT.
  ⚠️ The weak link: while the OAuth client is in *Testing* status, the Google
  refresh token expires 7 days after consent. Set the client to *In production*
  (unverified is fine) in the GCP console.
- **Steps**: pushed server-side to `POST /api/v3/walk/bulk` (`[{"date": "YYYY-MM-DD",
  "steps": N}]`, per-day upsert) before every claim pass. Source: the
  **Google Health API** (`dailyRollUp` on the `steps` data type) — the
  cloud store the Google Health app on your phone (the app that was Google
  Fit) syncs in the background: phone pedometer, Health Connect and
  devices. The rollup reconciles overlapping sources (e.g. watch + phone)
  into one total. The Health grant lives in `steps.health` and may be a
  *different* Google account from the Charlie login one:
  `python3 bootstrap.py --health` (credentials come from the config file;
  pick that account in the browser; the granted account is logged for
  verification).
  Guarded upsert: a day is only pushed when the Health store has data for
  it and the total is *higher* than what the server already holds —
  under-counted days get backfilled, today keeps refreshing, nothing is
  ever lowered.
  Step sync stays **off** until `bootstrap.py --health` has written the
  grant (no grant → the pass never runs); afterwards `steps.enabled`
  (master) or `steps.health.enabled` (Health source) act as kill switches.
  Keep the Google Health app installed and running on your phone so the
  cloud store fills up. (The old Google Fit REST API is deprecated in
  2026 and not used.)
- **Claim**: `POST /api/v3/donut/events` `{"eventId": N}` when the event is `isClaimable`.
  IDs: `1` daily · `6` 5,000 steps · `7` 10,000 steps · `2` ad-bonus (off by default).
- **Missions**: `GET /api/v3/mission/v2/active`, then `POST /api/v3/mission/{id}/complete`
  for every mission with `progress.isCompletable` (boosters, monthly honorary,
  milestones) — rewards: donuts, badges, items.

## Setup

1. **GCP, one time** (console.cloud.google.com):
   - Create a [desktop OAuth client](https://support.google.com/cloud/answer/6158849)
     (Credentials → *Create OAuth client ID* → *Desktop app* — no extra fields).
   - Enable the **Google Health API** (APIs & Services → Library) — the
     *Health* API; the old Fit API is deprecated and no longer available to
     new signups.
   - Set the OAuth consent screen to *In production* (unverified is fine) —
     while in *Testing*, Google refresh tokens expire 7 days after consent.
     *External* production mode requires filling in the **Branding** page
     first (app name, support email, homepage URL, privacy policy URL —
     Google doesn't verify the content); *internal* mode only works with
     Google Workspace accounts in the same GCP org, not Gmail. After
     publishing, re-run both bootstraps so fresh (non-expiring) refresh
     tokens are issued.

2. **Bootstrap, on a machine with a browser** ([OAuth 2.0 for native apps](https://developers.google.com/identity/protocols/oauth2/native-app),
   loopback redirect + PKCE; `bootstrap.py` is that flow in ~150 lines):

   ```bash
   python3 bootstrap.py <client_id> <client_secret>
   # open the printed URL, pick the Google account your Charlie account uses
   # → writes ./charlie-replay.json and verifies the session

   python3 bootstrap.py --health
   # credentials now come from the config file; pick the account that has
   # the Google Health app on the phone (the app that was Google Fit; may be
   # a different account) → stored in steps.health; the granted account is
   # logged for verification, with a warning if it matches the Charlie login
   # account
   ```

3. **Run**:

   ```bash
   docker compose up -d
   docker compose logs -f
   ```

   No Docker? `python3 charlie_replay.py --loop`

## Ops

```bash
python3 charlie_replay.py --status    # balance + claimable state
python3 charlie_replay.py --once      # single pass
python3 charlie_replay.py --relogin   # force a fresh Charlie JWT
docker compose logs -f                # watch the loop
```

Config: `charlie-replay.json` (chmod 600, never commit — contains live tokens).
Edit `claim_ids` / `interval_minutes` / the `steps` section to taste; the file is
read on each pass.

## Layout

```
bootstrap.py        one-time OAuth + initial login (needs a browser)
charlie_replay.py   the daemon: session renewal + claim loop
Dockerfile          slim python image, loop mode
docker-compose.yml  mounts ./charlie-replay.json read/write
```
