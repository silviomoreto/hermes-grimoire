#!/bin/bash
# Start (idempotently) a dedicated headless Chrome for WhatsApp Web with a persistent profile,
# so the login survives restarts and redeploys. Prints "running", "started" or "failed".
# Env: WA_CDP_PORT (9333), WA_PROFILE_DIR (/data/browser/whatsapp), WA_LANG (en-US), CHROME (auto), TZ.
PORT=${WA_CDP_PORT:-9333}
PROFILE=${WA_PROFILE_DIR:-/data/browser/whatsapp}
LOG="${PROFILE%/}.log"
if curl -s -m 2 "http://127.0.0.1:$PORT/json/version" >/dev/null; then echo "running"; exit 0; fi
mkdir -p "$PROFILE"
# A recreated container leaves the old host's Singleton* files behind and Chrome refuses the profile.
rm -f "$PROFILE"/Singleton{Lock,Socket,Cookie} 2>/dev/null
if [ -z "${CHROME:-}" ]; then
  CHROME=$(ls -d /opt/hermes/tools/chromium-*/chrome-linux64/chrome 2>/dev/null | sort -V | tail -1)
  [ -z "$CHROME" ] && CHROME=$(command -v chromium || command -v chromium-browser || command -v google-chrome || true)
fi
[ -z "$CHROME" ] && { echo "failed: no Chrome/Chromium found (set CHROME=...)"; exit 1; }
# WhatsApp rejects user agents containing "HeadlessChrome", so set a normal desktop UA.
setsid nohup "$CHROME" --headless=new --no-sandbox --disable-dev-shm-usage --no-first-run --no-default-browser-check \
  --disable-background-networking --remote-debugging-address=127.0.0.1 --remote-debugging-port="$PORT" \
  --user-data-dir="$PROFILE" --lang="${WA_LANG:-en-US}" --window-size=1280,900 \
  --user-agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36" \
  > "$LOG" 2>&1 < /dev/null &
for i in $(seq 1 20); do sleep 1; curl -s -m 2 "http://127.0.0.1:$PORT/json/version" >/dev/null && { echo "started"; exit 0; }; done
echo "failed"; tail -5 "$LOG"; exit 1
