# charlie-replay

Server-side donut claimer for the [Charlie Walking](https://play.google.com/store/apps/details?id=com.charlie.walking) app.
Claims the daily / 5k / 10k-step donut rewards against the app's private API — no app interaction, no ads.

> ⚠️ **Unofficial client on a private API.** Use at your own risk: the developer can
> restrict or terminate accounts at their discretion if they notice.

## Setup (≈5 min)

### 1. GCP, one time
[console.cloud.google.com](https://console.cloud.google.com):

1. Create a **Desktop OAuth client** (OAuth client ID → Desktop app).
2. *(Optional)* Enable the **Google Health API** (Library) — only if you want automatic step syncing. Without it you still claim the daily donut; the 5k/10k step donuts just won't auto-fill.
3. Set the OAuth consent screen to **In production** (unverified is fine).
   - *This matters:* while it's in *Testing*, refresh tokens expire after **7 days**.
   - *External* production mode needs the **Branding** page filled in first (app name,
     support email, homepage, privacy URL — content isn't verified). *Internal* mode
     only works with Google Workspace accounts in the same org, not Gmail.
   - After publishing, re-run both bootstraps below so fresh, non-expiring tokens issue.

### 2. Bootstrap login (required), on a machine with a browser
`bootstrap.py` is the [native OAuth flow](https://developers.google.com/identity/protocols/oauth2/native-app) (~150 lines):

```bash
python3 bootstrap.py <client_id> <client_secret>
# open the printed URL, pick the account your Charlie account uses
# → writes ./charlie-replay.json and verifies the session
```

### 3. Step sync (optional)

This auto-pushes your phone's step counts to the server so the **5k / 10k donuts** become claimable without the Charlie app on your phone. **Skip it if** you don't run the Google Health app, just want the daily donut, or don't want a second Google grant. (It may use a *different* Google account than your Charlie login.)

```bash
python3 bootstrap.py --health
# pick the account that has the Google Health app on your phone
# → stored in steps.health in charlie-replay.json
```

### 4. Run

```bash
docker compose up -d
docker compose logs -f
```

No Docker? `python3 charlie_replay.py --loop`

If you set up step sync above, keep the Google Health app installed and running on your
phone so step data keeps syncing.

## Ops

```bash
python3 charlie_replay.py --status    # balance + claimable state
python3 charlie_replay.py --once      # single pass
python3 charlie_replay.py --relogin   # force a fresh Charlie JWT
docker compose logs -f                # watch the loop
```

Config: `charlie-replay.json` (chmod 600, never commit — contains live tokens).
Edit `claim_ids` / `interval_minutes` / the `steps` section to taste; it's re-read each pass.

## How it works

A short version: `bootstrap.py` runs the Google OAuth flow and writes credentials to
`charlie-replay.json`. The daemon then loops every `interval_minutes`: it renews the
Charlie JWT from the Google refresh token, pushes recent step totals from Google Health,
claims any claimable donut event, and completes eligible missions. That's it — everything
else is in the code (`charlie_replay.py`).

## API reference

Charlie API base: `https://charlieapp-prod.nombs.site/api/v3`, auth `Authorization: Bearer <jwt>`.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/auth/login/google` | Replay Google login → `{accessToken, refreshToken}` JWT pair |
| GET  | `/donut/events` | List events; each has `id`, `isClaimable`, `claimedCount/claimableCount` |
| POST | `/donut/events` | Claim: body `{"eventId": N}` → `{success, data: {donuts, balance}}` |
| GET  | `/donut/balance` | `{balance}` donuts |
| GET  | `/mission/v2/active` | Active missions; complete those with `progress.isCompletable` |
| POST | `/mission/{id}/complete` | Complete a mission → `rewarded` (`donuts` \| `badge` \| `item`) |
| GET  | `/walk/calendar/month` | `{walks: [{localDateString, steps}]}` — read to guard upserts |
| GET  | `/walk/today` | Today's server step count |
| POST | `/walk/bulk` | Push step totals: body `[{date, steps}]`, per-day upsert |

Event IDs: `1` daily · `6` 5k steps · `7` 10k steps · `2` ad bonus (opt-in).

Health data comes from Google Health's `dailyRollUp` (reconciled per-day step totals from
the phone's Google Health app) via its own grant stored in `steps.health`.
