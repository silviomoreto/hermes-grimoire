---
name: live-browser-handoff
description: "Use when the user must drive the agent's browser live."
---

# Live browser handoff

Your agent hits a captcha, an SMS or app 2FA prompt, or a password it must not know. Instead of giving up, it sends you a **one-time link**. You open it on your phone or laptop, see its headless Chrome live, tap and type, then press **Done**, and the agent carries on from the same logged-in page. The secret never goes through the chat.

> **Safety first.** Whoever holds the link controls a logged-in browser until the session ends. Send it only in your private chat with the agent, never in a group or channel. The agent must never open the link itself, because opening it burns the one-time token. Never share a browser profile that holds a messaging account or anything you would not hand over: put those ports on `LIVE_BROWSER_DENY_PORTS`.

## When to Use
- The user asks for it: "open the browser", "send me the browser link", `/browser`.
- A browser task is blocked on something only a human should do: a captcha, a 2FA code, approving a login on a phone, or a password that is not in the Hermes vault. For a plain email and password, prefer `hermes vault add` (the vault fills it without a human).
- The user wants to watch what the agent's browser is showing right now.

## How it works
- A dedicated headless Chrome (CDP port 9339 by default) with its own persistent profile. It starts on demand and stays up, so the logged-in session can be reused after the handoff.
- `scripts/live_browser.py` serves a small viewer (Python + aiohttp).
  - Chrome's `Page.startScreencast` sends JPEG frames out, capped at about 8 fps.
  - Clicks, typing and paste go back in through `Input.dispatchMouseEvent`, `dispatchKeyEvent` and `insertText`.
- Viewer controls:
  - ← back, ⟳ reload, address bar, ▤ tabs;
  - ⌨️ opens a field that brings up the phone keyboard and accepts paste from a password manager;
  - ✋ drag mode for slider captchas (by default a tap clicks and a swipe scrolls);
  - 📱 phone layout;
  - ✅ Done ends the session.
- Security:
  - the link carries a 32-byte random token that works **once** and only for 10 minutes;
  - opening it swaps the token for an HttpOnly, Secure, SameSite=Strict cookie;
  - a session lasts at most 30 minutes and ends after 10 idle minutes; then the server exits;
  - keystrokes and tokens are never logged.

## Setup
1. **Python with aiohttp and a Chrome/Chromium.** The Hermes venv already has aiohttp and Hermes ships a Chromium. The script finds it under `/opt/hermes/tools/chromium-*`, in the Playwright cache or on `PATH`. Otherwise set `LIVE_BROWSER_CHROME`.
2. **An https URL that reaches the viewer port.** The script listens on `LIVE_BROWSER_LISTEN_PORT` (default `$PORT` or 8080) and builds the link from `LIVE_BROWSER_PUBLIC_URL`.
   - **Railway:** nothing to set. It uses `RAILWAY_PUBLIC_DOMAIN` and `$PORT`/8080, the port the service domain routes to. Check first that nothing else listens there: `curl -s https://<domain>/` should answer 502 between sessions.
   - **Elsewhere:** set `LIVE_BROWSER_PUBLIC_URL` to your host's public https URL. If you publish it through a reverse tunnel you already run, also set `LIVE_BROWSER_LISTEN_HOST=127.0.0.1` and point the tunnel at the port.
3. **Optional settings**, as environment variables or as `KEY=VALUE` lines in `scripts/live_browser.env`. Real environment variables win.
   - `LIVE_BROWSER_ALLOWED_PORTS=9334,9339`: other dedicated Chromes that may be shared.
   - `LIVE_BROWSER_DENY_PORTS=9333`: Chromes that can never be shared, for example a messaging app.
   - `LIVE_BROWSER_STATE_DIR` and `LIVE_BROWSER_PROFILE_DIR`: defaults under `$HERMES_HOME/live-browser`.
   - `TZ`: time zone of the times in the link message.
4. **One-tap command (recommended).** Add a quick command, so the link arrives even while the agent is busy. Then **restart the gateway**: it reads `config.yaml` only at startup, and until then `/browser` answers "Unknown command".
   ```yaml
   quick_commands:
     browser:
       type: exec
       command: /opt/hermes/.venv/bin/python <skill dir>/scripts/live_browser.py start
   ```
   Quick commands run for any allowed user. Keep `*_ALLOWED_USERS` to yourself.

## Commands
```bash
PY=/opt/hermes/.venv/bin/python; LB=<skill dir>/scripts/live_browser.py
$PY $LB start --url https://example.com/login   # prints the link (about 1 s with a public URL)
$PY $LB wait --timeout 600                      # blocks until Done, then prints status JSON
$PY $LB status                                  # active/ended, reason, current URL
$PY $LB stop [--chrome]                         # end now (--chrome also frees the Chrome's RAM)
```
Flow for a blocked task:
1. `start --url <page>` to open the page in the dedicated Chrome.
2. Send the printed message to the user as is.
3. Run `wait`.
4. On `done: true`, continue in the same Chrome with your own CDP client on port 9339. browser_exec runs a different browser and cannot see this one.

## Pitfalls
- **`/browser` is also a built-in Hermes command, but CLI-only.** In Telegram/Slack the quick command wins, since the built-in is not a gateway command. Pick another name if you use the CLI chat.
- **Prefer a stable public URL over a throwaway tunnel hostname.** A freshly created random hostname took minutes to resolve in testing, and probing it too early made the resolver cache NXDOMAIN.
- **Two windows with the same cookie** used to kick each other off every couple of seconds. A new window now takes over, and the old one shows "session opened in another window" and stops reconnecting.
- **Do not enable `Emulation.setTouchEmulationEnabled`** for the phone layout: it swallowed the viewer's mouse events. Device metrics alone are enough.
- **The default headless user agent** (`HeadlessChrome`) is flagged by many login pages. The script launches Chrome with a regular desktop user agent for its own version.
- **Test without burning a real session.** Use a small client: GET `/s/<token>` keeping the cookie, open `/ws` with `Origin` set, send `{"type":"text"}`, then read the input value through CDP. Automating the viewer page from another headless browser works with mouse clicks and `Input.insertText`. `Input.dispatchTouchEvent` can hang there.
