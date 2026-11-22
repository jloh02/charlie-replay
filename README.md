# charlie-replay

Server-side donut claimer for the [Charlie Walking](https://play.google.com/store/apps/details?id=com.charlie.walking) app.
Claims the daily / 5k / 10k-step donut rewards against the app's private API — no app interaction, no ads.

> ⚠️ Unofficial client on a private API. The app has no published terms of service
> (its only legal document is a privacy policy that doesn't restrict API use), but
> account restriction/termination remains the developer's unilateral right if they
> notice. Use at your own risk.

## How it works

- **Session**: Google OAuth replay → `POST /api/v3/auth/login/google` → Charlie JWT.
  Self-renewing chain: Google refresh token (long-lived) → Google access token (1 h) → Charlie JWT (7 d).
- **Claim**: `POST /api/v3/donut/events` `{"eventId": N}` when the event is `isClaimable`.
  IDs: `1` daily · `6` 5,000 steps · `7` 10,000 steps · `2` ad-bonus (off by default).
- **Missions**: `GET /api/v3/mission/v2/active`, then `POST /api/v3/mission/{id}/complete`
  for every mission with `progress.isCompletable` (boosters, monthly honorary,
  milestones) — rewards: donuts, badges, items.
- **Steps** are uploaded to the server *by the app on your phone*. Keep the official app
  installed and signed in so step milestones can become claimable.

## Setup

1. **One-time, on a machine with a browser** — create a desktop OAuth client
   (console.cloud.google.com → Credentials → *Create OAuth client ID* → *Desktop app*), then:

   ```bash
   python3 bootstrap.py <client_id> <client_secret>
   # open the printed URL, pick the Google account your Charlie account uses
   # → writes ./charlie-replay.json and verifies the session
   ```

2. **Run**:

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
Edit `claim_ids` / `interval_minutes` to taste; the file is read on each pass.

## Layout

```
bootstrap.py        one-time OAuth + initial login (needs a browser)
charlie_replay.py   the daemon: session renewal + claim loop
Dockerfile          slim python image, loop mode
docker-compose.yml  mounts ./charlie-replay.json read/write
```
