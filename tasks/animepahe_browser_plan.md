# Animepahe browser-backed transport plan

## Goal

Make the legacy Python app usable against the current Animepahe `.pw` challenge without automating or bypassing the challenge.

## Supported boundary

- A real, visible Playwright browser is launched lazily.
- The user manually completes any interactive challenge in that browser.
- Requests are made through the browser context after the challenge clears.
- Cookies remain inside the in-memory browser context; they are not exported, logged, or written to the repository/settings.
- No CAPTCHA solving, TLS impersonation, fingerprint spoofing, or automated challenge replay.

## Implementation slices

1. Add a lazy `BrowserSession` worker with a request queue, bounded user-interaction wait, and an in-memory response adapter.
2. Route Animepahe page/API/form requests through the session, retaining the existing typed `InvalidDownloadResponse` handling.
3. Add offline fake-transport regressions and dependency/build documentation.
4. Independently review and verify GUI/CLI lifecycle, cancellation, and no-secret behavior.

## Dependency and release implications

- Playwright becomes a runtime dependency; users also need a Chromium install (`playwright install chromium`) or a documented supported browser channel.
- The wheel can build without bundling browser binaries; the release guide must state the browser setup explicitly.
- If Playwright or a browser is unavailable, Pahe fails with an actionable setup error rather than falling back silently to a known-blocked requests session.

## Current evidence

Upstream v3.0.0 uses an embedded browser transport and waits for user interaction; it is a separate Flutter/Dart architecture, not a drop-in Python patch. The legacy app currently has no browser dependency or transport.

A real Playwright/Chromium probe launched the visible browser against `https://animepahe.pw/`, detected the interactive challenge, and timed out waiting for manual verification as designed. No challenge was solved automatically and no cookies were exported.
