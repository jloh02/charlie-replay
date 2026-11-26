# Privacy Policy — charlie-replay

**Effective date:** 2026-11-26

## What this is

**charlie-replay** is a small personal automation script that runs on a single
owner's own machine (or in a container on their own infrastructure). It is not a
website or a multi-user service: there are no users to register, no accounts hosted
here, and no data stored on any server operated by the owner of this repository.
This policy describes what the software does with data while it runs.

## Information we do not collect

The software collects **no** personal information from anyone: no account data,
no cookies, no analytics, no tracking, no logs forwarded anywhere. All processing
happens locally on the owner's machine.

## What the software does with third-party data

While running, the software:

- Signs in to the Charlie Walking app (`charlieapp-prod.nombs.site`) on the owner's
  behalf using a standard Google OAuth 2.0 flow for desktop apps (authorization
  code + PKCE, redirect to a local loopback address). The Google scopes requested
  for this are `openid`, `email` and `profile`.
- Reads **daily step-count rollups only** from the owner's Google Health store via
  the Google Health API, using the read-only scope
  `googlehealth.activity_and_fitness.readonly`. No other Health data type is
  requested or read.
- Uploads those daily step totals to the owner's own Charlie Walking account and
  claims the resulting rewards in that same account.

OAuth access tokens, refresh tokens and the Charlie session are stored in a single
local configuration file with restrictive file permissions (owner read/write only).
They are sent only to `oauth2.googleapis.com`, `www.googleapis.com` (Google Health)
and `charlieapp-prod.nombs.site` (Charlie Walking), and nowhere else.

## Third-party services

- **Google** — provides the OAuth sign-in and the Health data store. Google's own
  privacy policy applies to the data it holds (<https://policies.google.com/privacy>).
  The owner can revoke access to this application at
  <https://myaccount.google.com/permissions> at any time.
- **Charlie Walking** (operated by Nombs) — receives the owner's step totals and
  session tokens as described above. Charlie Walking's own privacy policy applies
  to data sent to that service.

## Changes

If the software's behaviour changes (for example, additional data types are read),
this page will be updated and the effective date above changed.
