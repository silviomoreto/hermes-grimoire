---
name: whatsapp-web
description: Use when Hermes must read or send on the user's WhatsApp.
---

# WhatsApp Web: your agent reads and sends on your own WhatsApp

Drives the user's **own** WhatsApp account through WhatsApp Web, in a dedicated headless Chrome with a persistent profile. The agent can read a chat, draft replies, send text and images, and watch for answers (a pharmacy quote, a supplier, a doctor's office).

> ⚠️ **Unofficial automation.** WhatsApp's terms do not allow automated clients. Keep it human-scale: one person's account, messages the user approved, no bulk sending. A number can get banned. For bots that talk to customers, use the official WhatsApp Business API instead.

## When to Use
- The user says "send X to Y on WhatsApp", "check what Z answered", or "ask the pharmacy for a quote and tell me".
- Hermes' built-in WhatsApp gateway is a different thing: it makes Hermes reachable as a chat bot. This skill makes Hermes act as the user inside the user's own WhatsApp.

## Rules (agree on them with the user first)
1. **Nothing goes out without approval.** Show the exact text (and image + caption) first. Send only after the user says "send". A direct, short order with the text already given ("tell Ana I'm 5 min late") counts as approval.
2. **Open only the chat of the task.** Find chats through search, not by scrolling the chat list. Report anything seen in passing (other chat titles, message previews) instead of hiding it.
3. **Messages to third parties use a neutral tone,** in the user's name, never the assistant's persona.
4. **A late "send" is not a new order.** If the user's "send" arrives after the message already went out (messages cross), check the last row of the chat and answer "already sent at HH:MM". Resending duplicates it for the contact.
5. **Payments, personal documents (ID numbers) and anything irreversible** need an explicit ok in the conversation, even when the other side asks for them.

## Setup
1. Copy `scripts/` to the server (e.g. `/data/tools/`). Requirements: Chrome/Chromium and the Python `websockets` package.
2. Start the browser: `scripts/wa-browser.sh`. It defaults to port 9333 and profile `/data/browser/whatsapp`; put the profile on the persistent volume.
3. Run `wa.py status`. It returns `logged_in`, `logged_out` or `loading` (wait ~15 s while `loading`; search finds nothing then).
4. **Log in without a QR code:** run `wa.py login-code <phone digits>`, which prints an 8-character code. On the phone: Linked devices → Link a device → Link with phone number instead, then type the code. Codes expire in minutes; generate another if needed. For countries other than Brazil, set `WA_COUNTRY`, `WA_COUNTRY_RE` and `WA_DIAL_CODE`.
5. The login lives in the profile on disk. It survives Chrome restarts and redeploys. It only drops if the phone stays offline for ~14 days or the device is removed.

## Commands
- `wa.py search "<query>"`: the chat titles that match the query. Use it to find the exact chat name. It also "primes" the search box when `read` or `send` say the chat was not found.
- `wa.py read "<exact chat name>" [n]`: the last n rows, labeled `ME:` or `THEM:` by bubble side. Trust the label.
- `wa.py send "<chat>" "<text>"`: types the text, checks the box holds exactly that text, then presses Enter. If the text differs, it does not send.
- `wa.py send-image "<chat>" <file.jpg> "<caption>" --dry`: always run this first. It opens the preview, checks the send button and discards. Then run it again without `--dry`. Convert big PNGs to JPG first (`ffmpeg -i in.png -q:v 3 out.jpg`).
- After sending, `read "<chat>" 2` proves it went out. Don't keep following the chat unless asked.

## Watching for a reply (no AI, no tokens)
For "tell me when they answer", use a no-agent cron script instead of an AI routine:
- Every 5 min it runs `wa.py read "<chat>" 15` and prints only the new `THEM:` rows. Hermes delivers the output to the chat; empty output stays silent.
- **Filter by time, not by anchor.** A reopened chat renders only the last ~4 rows, so your own request scrolls out of view. Keep the rows whose `HH:MM` is at or after the request time, and remember the ones already forwarded in a small state file. With an anchor message instead, the watcher goes silent exactly when the answer arrives.
- Quotes often come as an image. Take a screenshot (`wa.py shot`) and read it with vision; the text rows only show the caption.
- If a run cannot open the chat 2 times in a row, the script should say so instead of staying silent.
- Remove the cron when the task is done.

## Pitfalls
- **The chat is not found even though it exists.** The search sometimes ignores the first typing burst. Run `wa.py search "<name>"` and retry. The chat title must match exactly; contacts can be saved with a different spelling than the business name.
- **"WhatsApp is open in another window":** click "Use here" and close the duplicate tab (`curl 127.0.0.1:9333/json/close/<id>`). Never open web.whatsapp.com in another browser session at the same time.
- **A "What's new" modal blocks clicks.** `wa.py` closes it.
- **Chats only open with real mouse events** (`Input.dispatchMouseEvent` on the chat title). Synthetic JS clicks don't open them.
- **A discarded image caption stays as a draft** in the chat footer. `--dry` already clears it; check the footer is empty before a real send.
- **Headless UA:** WhatsApp shows "update Chrome" to user agents containing "HeadlessChrome". `wa-browser.sh` sets a normal UA.
- **The country picker on the login screen** often defaults to the wrong country. `login-code` picks it by `WA_COUNTRY_RE`.
- **Don't `pkill -f` the profile path** from the agent's terminal; it can kill the agent's own shell. Use `pgrep` + `kill <pid>`.
- **RAM:** an open WhatsApp Web Chrome uses ~1.5–2 GB. Close it after ~30 min idle and restart it on demand (see `hermes-railway-savings`). Reopening takes ~20–30 s and keeps the login.
- **Times in messages are the browser's timezone.** Set `TZ` before starting Chrome. When writing a greeting to a contact abroad, check the contact's local time in the same turn.
