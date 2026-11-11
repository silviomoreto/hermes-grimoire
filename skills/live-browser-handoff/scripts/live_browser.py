#!/usr/bin/env python3
"""Live browser handoff: let a human drive the agent's headless Chrome through a one-time link.

The agent gets stuck on a captcha, an SMS/app 2FA prompt or a password it must not know.
It runs `start`, sends the printed link to its human, and waits. The human opens the link
on a phone or laptop, sees the page live, taps and types, then presses Done. The secret
never goes through the chat.

  live_browser.py start [--url URL] [--cdp PORT] [--minutes 30] [--open-minutes 10] [--json]
  live_browser.py wait [--timeout 600]   # block until Done is pressed or the session ends
  live_browser.py status                 # JSON: active/ended, reason, current URL
  live_browser.py stop [--chrome]        # end the session (--chrome also kills the dedicated Chrome)
  live_browser.py serve                  # internal: the web server started by `start`

How it works: Chrome DevTools Protocol screencast (JPEG frames, ~8 fps) out to the viewer,
Input.dispatchMouseEvent / dispatchKeyEvent / insertText back in. Python 3.9+ and aiohttp.

Transport: the server listens on LIVE_BROWSER_LISTEN_PORT (default $PORT or 8080) and the
link uses LIVE_BROWSER_PUBLIC_URL (or https://$RAILWAY_PUBLIC_DOMAIN on Railway). Point that URL
at the port: the platform's own public domain, or a reverse tunnel you already run (then set
LIVE_BROWSER_LISTEN_HOST=127.0.0.1). Nothing listens on the port between sessions.

Settings come from environment variables, optionally from a `live_browser.env` file
(KEY=VALUE lines) next to this script; real environment variables win:
  LIVE_BROWSER_STATE_DIR      default $HERMES_HOME/live-browser (or ~/.hermes/live-browser)
  LIVE_BROWSER_PROFILE_DIR    dedicated Chrome profile, default <state dir>/chrome-profile
  LIVE_BROWSER_CDP_PORT       dedicated Chrome DevTools port, default 9339
  LIVE_BROWSER_ALLOWED_PORTS  comma list of CDP ports that may be shared (default: the dedicated one)
  LIVE_BROWSER_DENY_PORTS     comma list that can never be shared, even if allowed (e.g. a messaging app)
  LIVE_BROWSER_CHROME         Chrome/Chromium binary (auto-detected otherwise)
  LIVE_BROWSER_CHROME_LANG    --lang for the dedicated Chrome, default en-US
  LIVE_BROWSER_LISTEN_HOST    interface to bind, default all (use 127.0.0.1 behind a local tunnel)
  TZ                          time zone of the times printed in the link message (e.g. Europe/Lisbon)

Security model: the link carries a 32-byte random token that works once and only for
--open-minutes. Opening the link only shows a button (chat apps fetch links to build previews);
tapping it spends the token and swaps it for an HttpOnly, Secure, SameSite=Strict cookie.
Sessions end after --minutes, after 10 idle minutes, or when Done is pressed; then the
server exits. Keystrokes and tokens are never logged.
"""
import argparse, asyncio, datetime, glob, json, os, re, secrets, shutil, signal, subprocess, sys, time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def _env_file():
    path = os.path.join(HERE, "live_browser.env")
    values = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    return values


_FILE = _env_file()


def setting(name, default=""):
    """Environment variable first, then live_browser.env next to this script, then the default."""
    return os.environ.get(name) or _FILE.get(name) or default


def _ports(name, default=""):
    return {int(p) for p in setting(name, default).replace(" ", "").split(",") if p}


STATE_DIR = setting("LIVE_BROWSER_STATE_DIR") or os.path.join(
    setting("HERMES_HOME") or os.path.expanduser("~/.hermes"), "live-browser")
STATE = os.path.join(STATE_DIR, "state.json")
SERVER_LOG = os.path.join(STATE_DIR, "server.log")
CHROME_LOG = os.path.join(STATE_DIR, "chrome.log")
LIVE_PORT = int(setting("LIVE_BROWSER_CDP_PORT", "9339"))
LIVE_PROFILE = setting("LIVE_BROWSER_PROFILE_DIR") or os.path.join(STATE_DIR, "chrome-profile")
ALLOWED_CDP = _ports("LIVE_BROWSER_ALLOWED_PORTS", str(LIVE_PORT)) | {LIVE_PORT}
FORBIDDEN_CDP = _ports("LIVE_BROWSER_DENY_PORTS")
_railway = setting("RAILWAY_PUBLIC_DOMAIN")
PUBLIC_URL = (setting("LIVE_BROWSER_PUBLIC_URL") or (f"https://{_railway}" if _railway else "")).rstrip("/")
LISTEN_PORT = int(setting("LIVE_BROWSER_LISTEN_PORT") or setting("PORT") or "8080")
LISTEN_HOST = setting("LIVE_BROWSER_LISTEN_HOST") or None  # None = every interface, IPv4 and IPv6
TZ_NAME = setting("TZ")
IDLE_SECONDS = 600

TEXT = {
    "title": "Agent's browser", "url": "address", "back": "Back", "reload": "Reload", "tabs": "Tabs",
    "kb": "Keyboard", "drag": "Drag mode (slider captchas)", "mob": "Phone layout", "done": "✅ Done",
    "kbd": "type here (Enter sends Enter)", "connecting": "connecting…", "reconnecting": "reconnecting…",
    "drag_on": "drag mode: your finger holds and drags", "drag_off": "normal mode: tap clicks, swipe scrolls",
    "newtab": "+ new tab", "confirm": "End the session and hand the browser back to the agent?",
    "failed": "that failed, try again", "elsewhere": "session opened in another window",
    "ended": "session ended", "ended_done": "✅ Done! The browser is back with the agent.",
    "expired": "link expired", "maxtime": "maximum session time reached", "idle": "session ended for inactivity",
    "bad_link": "Invalid, expired or already used link. Ask the agent for a new one.",
    "no_session": "No session. Ask the agent for a new link.",
    "open": "Open the live browser", "open_hint": "Tap to take control. This link works once.",
    "msg": "🖥️ Live browser\n{link}\n\nOpen by {open_by} · works once · ends by {ends_by}.\nWhen finished, tap ✅ Done.",
    "r_done": "finished by the user", "r_unopened": "link expired unopened", "r_max": "max time",
    "r_idle": "idle", "r_stopped": "stopped by the agent", "r_replaced": "replaced by a new session",
}


# ---------------------------------------------------------------- state helpers
def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    tmp = STATE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(st, f)
    os.replace(tmp, STATE)


def alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill(pid):
    if alive(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass


def cdp_up(port):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2).read()
        return True
    except Exception:
        return False


def hhmm(ts):
    if TZ_NAME:
        try:
            from zoneinfo import ZoneInfo
            return datetime.datetime.fromtimestamp(ts, ZoneInfo(TZ_NAME)).strftime("%H:%M")
        except Exception:
            pass
    return time.strftime("%H:%M", time.localtime(ts))


# ---------------------------------------------------------------- chrome
def find_chrome():
    if setting("LIVE_BROWSER_CHROME"):
        return setting("LIVE_BROWSER_CHROME")
    found = sorted(glob.glob("/opt/hermes/tools/chromium-*/chrome-linux64/chrome")) + sorted(
        glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")))
    if found:
        return found[-1]
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome"):
        if shutil.which(name):
            return shutil.which(name)
    sys.exit("Chrome/Chromium not found; set LIVE_BROWSER_CHROME")


def ensure_live_chrome():
    if cdp_up(LIVE_PORT):
        return
    os.makedirs(LIVE_PROFILE, exist_ok=True)
    for n in ("SingletonLock", "SingletonSocket", "SingletonCookie"):  # stale locks after a container restart
        try:
            os.remove(os.path.join(LIVE_PROFILE, n))
        except FileNotFoundError:
            pass
    chrome = find_chrome()
    try:  # a regular desktop user agent: the default headless one is flagged by many login pages
        major = re.search(r"(\d+)\.", subprocess.run([chrome, "--version"], capture_output=True, text=True, timeout=10).stdout).group(1)
    except Exception:
        major = "140"
    ua = f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    log = open(CHROME_LOG, "ab")
    subprocess.Popen(
        [chrome, "--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--no-first-run",
         "--no-default-browser-check", "--disable-background-networking",
         "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={LIVE_PORT}",
         f"--user-data-dir={LIVE_PROFILE}", f"--lang={setting('LIVE_BROWSER_CHROME_LANG', 'en-US')}",
         "--window-size=1280,900", f"--user-agent={ua}", "about:blank"],
        stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(40):
        time.sleep(0.5)
        if cdp_up(LIVE_PORT):
            return
    sys.exit(f"dedicated Chrome did not start; see {CHROME_LOG}")


def navigate_first_page(port, url):
    async def go():
        import aiohttp
        async with aiohttp.ClientSession() as http:
            async with http.get(f"http://127.0.0.1:{port}/json/list") as r:
                pages = [t for t in await r.json(content_type=None) if t["type"] == "page"]
            if not pages:
                async with http.put(f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote(url, safe=':/?&=%#')}") as r:
                    await r.read()
                return
            async with http.ws_connect(pages[0]["webSocketDebuggerUrl"], max_msg_size=0) as ws:
                await ws.send_json({"id": 1, "method": "Page.navigate", "params": {"url": url}})
                async for m in ws:
                    if json.loads(m.data).get("id") == 1:
                        break
    asyncio.run(asyncio.wait_for(go(), 20))


# ---------------------------------------------------------------- commands
def cmd_stop(args, reason=None, quiet=False):
    st = load_state()
    kill(st.get("server_pid"))
    reason = reason or TEXT["r_stopped"]
    if st and not st.get("ended_at"):
        st.update(ended_at=time.time(), reason=reason)
        save_state(st)
    if getattr(args, "chrome", False):
        subprocess.run(["pkill", "-f", f"remote-debugging-port={LIVE_PORT}"], check=False)
    if not quiet:
        print(json.dumps({"stopped": True, "reason": st.get("reason", reason) if st else reason}, ensure_ascii=False))


def cmd_status(args):
    st = load_state()
    if not st:
        print(json.dumps({"state": "none"}))
        return
    out = {k: st.get(k) for k in ("cdp", "claimed", "done", "reason", "last_url")}
    out["state"] = "ended" if st.get("ended_at") or not alive(st.get("server_pid")) else "active"
    out["started"] = hhmm(st["created_at"]) if st.get("created_at") else None
    out["ends_by"] = hhmm(st["hard_deadline"]) if st.get("hard_deadline") else None
    print(json.dumps(out, ensure_ascii=False))


def cmd_wait(args):
    t0 = time.time()
    while time.time() - t0 < args.timeout:
        st = load_state()
        if st.get("done") or st.get("ended_at") or not alive(st.get("server_pid")):
            break
        time.sleep(2)
    cmd_status(args)


def cmd_start(args):
    port = args.cdp
    if port in FORBIDDEN_CDP:
        sys.exit(f"port {port} is on LIVE_BROWSER_DENY_PORTS and can never be shared")
    if port not in ALLOWED_CDP:
        sys.exit(f"port {port} is not in LIVE_BROWSER_ALLOWED_PORTS {sorted(ALLOWED_CDP)}")
    if not PUBLIC_URL:
        sys.exit("set LIVE_BROWSER_PUBLIC_URL (the https URL that reaches LIVE_BROWSER_LISTEN_PORT); see --help")
    cmd_stop(argparse.Namespace(chrome=False), reason=TEXT["r_replaced"], quiet=True)
    if port == LIVE_PORT:
        ensure_live_chrome()
    elif not cdp_up(port):
        sys.exit(f"no Chrome answering on CDP port {port}")
    if args.url:
        navigate_first_page(port, args.url)

    now = time.time()
    st = {"cdp": port, "token": secrets.token_urlsafe(32), "sid": None, "claimed": False, "done": False,
          "created_at": now, "open_deadline": now + args.open_minutes * 60,
          "hard_deadline": now + args.minutes * 60, "ended_at": None, "reason": None, "last_url": args.url,
          "listen_port": LISTEN_PORT}
    token = st["token"]
    save_state(st)

    slog = open(SERVER_LOG, "ab")
    srv = subprocess.Popen([sys.executable, os.path.abspath(__file__), "serve"], stdout=slog, stderr=slog,
                           stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(40):
        time.sleep(0.25)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{st['listen_port']}/health", timeout=1).read()
            break
        except Exception:
            pass
    else:
        kill(srv.pid)
        sys.exit("server did not start; see " + SERVER_LOG)

    host = PUBLIC_URL
    st = load_state()
    st.update(server_pid=srv.pid, host=host)
    save_state(st)
    ready = False
    for _ in range(args.probe):
        try:
            with urllib.request.urlopen(urllib.request.Request(host + "/health", headers={"User-Agent": "live-browser"}), timeout=4) as r:
                ready = r.status == 200
        except Exception:
            ready = False
        if ready:
            break
        time.sleep(1)
    link = f"{host}/s/{token}"
    if args.json:
        print(json.dumps({"link": link, "ready": ready, "open_by": hhmm(st["open_deadline"]),
                          "ends_by": hhmm(st["hard_deadline"]), "cdp": port}))
    else:
        print(TEXT["msg"].format(link=link, open_by=hhmm(st["open_deadline"]), ends_by=hhmm(st["hard_deadline"])))


# ---------------------------------------------------------------- viewer page
PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="robots" content="noindex"><title></title>
<style>
:root{color-scheme:dark}
body{margin:0;background:#0b0b0f;color:#ddd;font:14px system-ui,sans-serif;overflow:hidden;height:100vh;display:flex;flex-direction:column}
#bar{display:flex;gap:4px;padding:6px;background:#141419;align-items:center;flex-wrap:wrap}
#bar button{background:#22222b;color:#eee;border:1px solid #333;border-radius:6px;padding:6px 9px;font-size:15px}
#bar button.on{background:#4b2a6b}
#url{flex:1;min-width:120px;background:#0b0b0f;color:#eee;border:1px solid #333;border-radius:6px;padding:6px}
#kbd{width:100%;box-sizing:border-box;background:#0b0b0f;color:#eee;border:1px solid #4b2a6b;border-radius:6px;padding:8px;font-size:16px;display:none}
#wrap{flex:1;overflow:hidden;display:flex;justify-content:center;align-items:flex-start;background:#000}
#screen{max-width:100%;max-height:100%;touch-action:none;user-select:none;-webkit-user-select:none;cursor:default}
#msg{position:fixed;bottom:8px;left:8px;right:8px;text-align:center;color:#bbb;font-size:12px;pointer-events:none}
#tabs{position:fixed;top:48px;left:6px;right:6px;background:#141419;border:1px solid #333;border-radius:8px;display:none;max-height:60vh;overflow:auto;z-index:5}
#tabs div{padding:10px;border-bottom:1px solid #222}
#done{background:#1e5b3a!important}
</style></head><body>
<div id="bar">
<button id="back">←</button><button id="reload">⟳</button>
<input id="url" autocapitalize="off" autocorrect="off" spellcheck="false">
<button id="tabsb">▤</button><button id="kb">⌨️</button><button id="drag">✋</button><button id="mob">📱</button>
<button id="done"></button>
<input id="kbd" autocapitalize="off" autocorrect="off" autocomplete="off" spellcheck="false">
</div>
<div id="tabs"></div>
<div id="wrap"><img id="screen" draggable="false" alt=""></div>
<div id="msg"></div>
<script>
const T=__TEXT__;
const $=id=>document.getElementById(id);const img=$('screen'),msg=$('msg');
document.title=T.title;document.documentElement.lang='en';$('url').placeholder=T.url;$('kbd').placeholder=T.kbd;$('done').textContent=T.done;
[['back','back'],['reload','reload'],['tabsb','tabs'],['kb','kb'],['drag','drag'],['mob','mob']].forEach(([i,k])=>$(i).title=T[k]);
msg.textContent=T.connecting;
let ws,meta={deviceWidth:1280,deviceHeight:900,offsetTop:0},drag=false,mobile=false,ended=false;
function send(o){if(ws&&ws.readyState===1)ws.send(JSON.stringify(o))}
function connect(){
 ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
 ws.onopen=()=>{msg.textContent=''};
 ws.onmessage=e=>{const d=JSON.parse(e.data);
  if(d.type==='frame'){img.src='data:image/jpeg;base64,'+d.data;if(d.meta)meta=d.meta}
  else if(d.type==='url'){if(document.activeElement!==$('url'))$('url').value=d.url||''}
  else if(d.type==='tabs'){const t=$('tabs');t.innerHTML='';d.tabs.forEach(x=>{const r=document.createElement('div');r.textContent=(x.active?'● ':'')+(x.title||x.url);r.onclick=()=>{send({type:'switch',id:x.id});t.style.display='none'};t.appendChild(r)});const n=document.createElement('div');n.textContent=T.newtab;n.onclick=()=>{send({type:'newtab'});t.style.display='none'};t.appendChild(n);t.style.display='block'}
  else if(d.type==='end'){ended=true;msg.textContent=d.text||T.ended;ws.close()}
  else if(d.type==='info'){msg.textContent=d.text;setTimeout(()=>{if(msg.textContent===d.text)msg.textContent=''},3000)}};
 ws.onclose=()=>{if(!ended){msg.textContent=T.reconnecting;setTimeout(connect,1500)}};
}
connect();
function pos(e){const r=img.getBoundingClientRect();return{x:(e.clientX-r.left)*meta.deviceWidth/r.width,y:(e.clientY-r.top)*meta.deviceHeight/r.height+(meta.offsetTop||0)}}
function mods(e){return (e.altKey?1:0)|(e.ctrlKey||e.metaKey?2:0)|(e.shiftKey?8:0)}
let down=null,lastMove=0,scrolled=false;
img.addEventListener('pointerdown',e=>{e.preventDefault();img.setPointerCapture(e.pointerId);const p=pos(e);down={x:e.clientX,y:e.clientY,p,touch:e.pointerType!=='mouse'};scrolled=false;
 if(!down.touch||drag)send({type:'mouse',ev:'mousePressed',x:p.x,y:p.y,button:e.button===2?'right':'left',clickCount:e.detail||1,mod:mods(e)})});
img.addEventListener('pointermove',e=>{const now=Date.now();if(now-lastMove<30)return;lastMove=now;const p=pos(e);
 if(down&&down.touch&&!drag){const dy=down.y-e.clientY,dx=down.x-e.clientX;if(Math.abs(dy)>6||Math.abs(dx)>6){scrolled=true;send({type:'wheel',x:down.p.x,y:down.p.y,dx:dx*2,dy:dy*2});down.x=e.clientX;down.y=e.clientY}return}
 send({type:'mouse',ev:'mouseMoved',x:p.x,y:p.y,button:down?'left':'none',buttons:down?1:0,mod:mods(e)})});
img.addEventListener('pointerup',e=>{const p=pos(e);if(!down)return;
 if(down.touch&&!drag){if(!scrolled){send({type:'mouse',ev:'mousePressed',x:p.x,y:p.y,button:'left',clickCount:1});send({type:'mouse',ev:'mouseReleased',x:p.x,y:p.y,button:'left',clickCount:1})}}
 else send({type:'mouse',ev:'mouseReleased',x:p.x,y:p.y,button:e.button===2?'right':'left',clickCount:e.detail||1,mod:mods(e)});
 down=null;if(e.pointerType!=='mouse'&&$('kbd').style.display==='block')$('kbd').focus()});
img.addEventListener('contextmenu',e=>e.preventDefault());
img.addEventListener('wheel',e=>{e.preventDefault();const p=pos(e);send({type:'wheel',x:p.x,y:p.y,dx:e.deltaX,dy:e.deltaY})},{passive:false});
const SPECIAL=new Set(['Enter','Backspace','Tab','Escape','ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Delete','Home','End','PageUp','PageDown']);
document.addEventListener('keydown',e=>{const a=document.activeElement;if(a===$('url')||a===$('kbd'))return;
 if(SPECIAL.has(e.key)||e.ctrlKey||e.metaKey||e.altKey){e.preventDefault();send({type:'key',key:e.key,mod:mods(e)})}
 else if(e.key.length===1){e.preventDefault();send({type:'text',text:e.key})}});
document.addEventListener('paste',e=>{const a=document.activeElement;if(a===$('url')||a===$('kbd'))return;const t=e.clipboardData.getData('text');if(t){e.preventDefault();send({type:'text',text:t})}});
const kbd=$('kbd');
kbd.addEventListener('input',e=>{if(e.inputType&&e.inputType.startsWith('delete')){send({type:'key',key:'Backspace'})}else if(kbd.value){send({type:'text',text:kbd.value})}kbd.value=''});
kbd.addEventListener('keydown',e=>{if(SPECIAL.has(e.key)&&e.key!=='Backspace'){e.preventDefault();send({type:'key',key:e.key})}else if(e.key==='Backspace'&&!kbd.value){e.preventDefault();send({type:'key',key:'Backspace'})}});
$('kb').onclick=()=>{const on=kbd.style.display!=='block';kbd.style.display=on?'block':'none';$('kb').classList.toggle('on',on);if(on)kbd.focus()};
$('drag').onclick=()=>{drag=!drag;$('drag').classList.toggle('on',drag);msg.textContent=drag?T.drag_on:T.drag_off};
$('mob').onclick=()=>{mobile=!mobile;$('mob').classList.toggle('on',mobile);send({type:'mobile',on:mobile})};
$('back').onclick=()=>send({type:'back'});$('reload').onclick=()=>send({type:'reload'});
$('tabsb').onclick=()=>{const t=$('tabs');if(t.style.display==='block')t.style.display='none';else send({type:'tabs'})};
$('url').addEventListener('keydown',e=>{if(e.key==='Enter'){send({type:'navigate',url:$('url').value});$('url').blur()}});
$('done').onclick=()=>{if(confirm(T.confirm))send({type:'done'})};
</script></body></html>"""

KEYS = {
    "Enter": (13, "Enter", "\r"), "Backspace": (8, "Backspace", None), "Tab": (9, "Tab", None),
    "Escape": (27, "Escape", None), "ArrowLeft": (37, "ArrowLeft", None), "ArrowUp": (38, "ArrowUp", None),
    "ArrowRight": (39, "ArrowRight", None), "ArrowDown": (40, "ArrowDown", None), "Delete": (46, "Delete", None),
    "Home": (36, "Home", None), "End": (35, "End", None), "PageUp": (33, "PageUp", None), "PageDown": (34, "PageDown", None),
}


def char_key(c):
    if c.isascii() and c.isalpha():
        return ord(c.upper()), "Key" + c.upper()
    if c.isascii() and c.isdigit():
        return ord(c), "Digit" + c
    if c == " ":
        return 32, "Space"
    return 0, ""


class CDP:
    def __init__(self, ws):
        self.ws, self.n, self.pending = ws, 0, {}

    async def call(self, method, **params):
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.n] = fut
        await self.ws.send_json({"id": self.n, "method": method, "params": params})
        return await asyncio.wait_for(fut, 20)

    async def fire(self, method, **params):
        self.n += 1
        await self.ws.send_json({"id": self.n, "method": method, "params": params})

    async def pump(self, on_event):
        import aiohttp
        async for m in self.ws:
            if m.type != aiohttp.WSMsgType.TEXT:
                break
            d = json.loads(m.data)
            if "id" in d:
                fut = self.pending.pop(d["id"], None)
                if fut and not fut.done():
                    if "error" in d:
                        fut.set_exception(RuntimeError(d["error"].get("message")))
                    else:
                        fut.set_result(d.get("result", {}))
            else:
                on_event(d.get("method"), d.get("params", {}))
        for fut in self.pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("cdp closed"))


def log(text):
    print(f"{time.strftime('%H:%M:%S')} {text}", flush=True)


def serve():
    import logging
    from aiohttp import web, ClientSession, WSMsgType
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    st = load_state()
    base = f"http://127.0.0.1:{st['cdp']}"
    page = PAGE.replace("__TEXT__", json.dumps(TEXT, ensure_ascii=False))
    app_state = {"client": None, "last_seen": time.time(), "target": None}

    def persist(**kw):
        cur = load_state()
        cur.update(kw)
        save_state(cur)

    async def end(reason, text):
        persist(ended_at=time.time(), reason=reason)
        c = app_state["client"]
        if c is not None and not c.closed:
            try:
                await c.send_json({"type": "end", "text": text})
                await c.close()
            except Exception:
                pass
        await asyncio.sleep(0.3)
        os._exit(0)

    async def watchdog():
        while True:
            await asyncio.sleep(3)
            cur = load_state()
            now = time.time()
            if cur.get("ended_at"):
                await end(cur.get("reason") or TEXT["ended"], TEXT["ended"])
            if not cur.get("claimed") and now > cur["open_deadline"]:
                await end(TEXT["r_unopened"], TEXT["expired"])
            if now > cur["hard_deadline"]:
                await end(TEXT["r_max"], TEXT["maxtime"])
            c = app_state["client"]
            if cur.get("claimed") and (c is None or c.closed) and now - app_state["last_seen"] > IDLE_SECONDS:
                await end(TEXT["r_idle"], TEXT["idle"])

    def authed(request):
        cur = load_state()
        sid = request.cookies.get("lb_sid")
        return bool(cur.get("sid")) and sid is not None and secrets.compare_digest(sid, cur["sid"]) and not cur.get("ended_at")

    async def health(request):
        return web.Response(text="ok")

    def token_ok(cur, tok):
        return not (cur.get("ended_at") or cur.get("claimed") or time.time() > cur["open_deadline"]
                    or not secrets.compare_digest(tok, cur.get("token", "")))

    async def claim_page(request):
        # Chat apps (Telegram, Slack, WhatsApp) fetch links with GET to build previews. A GET that
        # consumed the token would burn it before the human taps, so GET only shows a button and
        # the token is spent by the POST that button sends.
        if not token_ok(load_state(), request.match_info["token"]):
            return web.Response(status=403, text=TEXT["bad_link"])
        html = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
                f'<title>{TEXT["title"]}</title></head>'
                '<body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;'
                'background:#0b0b0f;color:#ddd;font:16px system-ui,sans-serif;text-align:center">'
                '<form method="post"><button style="font-size:20px;padding:16px 28px;border-radius:10px;'
                'border:1px solid #4b2a6b;background:#22222b;color:#eee">' + TEXT["open"] + '</button>'
                '<p style="color:#999">' + TEXT["open_hint"] + '</p></form></body></html>')
        return web.Response(text=html, content_type="text/html", headers={
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"})

    async def claim(request):
        cur = load_state()
        if not token_ok(cur, request.match_info["token"]):
            return web.Response(status=403, text=TEXT["bad_link"])
        sid = secrets.token_urlsafe(32)
        persist(claimed=True, sid=sid, claimed_at=time.time(), token="")
        app_state["last_seen"] = time.time()
        resp = web.HTTPSeeOther("/")
        resp.set_cookie("lb_sid", sid, httponly=True, secure=True, samesite="Strict", max_age=4 * 3600)
        raise resp

    async def index(request):
        if not authed(request):
            return web.Response(status=403, text=TEXT["no_session"])
        return web.Response(text=page, content_type="text/html", headers={
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"})

    async def pages(http):
        async with http.get(f"{base}/json/list") as r:
            return [t for t in await r.json(content_type=None) if t["type"] == "page" and not t["url"].startswith("devtools://")]

    async def ws_handler(request):
        if not authed(request):
            return web.Response(status=403)
        origin = request.headers.get("Origin", "")
        if origin and origin.split("://", 1)[-1] != request.host:
            return web.Response(status=403)
        client = web.WebSocketResponse(heartbeat=20, max_msg_size=8 * 1024 * 1024)
        await client.prepare(request)
        old = app_state["client"]
        if old is not None and not old.closed:
            try:  # the older window stops reconnecting instead of fighting over the session
                await old.send_json({"type": "end", "text": TEXT["elsewhere"]})
            except Exception:
                pass
            await old.close()
        app_state["client"] = client
        app_state["last_seen"] = time.time()

        out = asyncio.Queue()
        frame = {"msg": None}
        wake = asyncio.Event()

        async def sender():  # one writer: control messages first, then only the latest frame
            while not client.closed:
                await wake.wait()
                wake.clear()
                while not out.empty():
                    await client.send_json(out.get_nowait())
                if frame["msg"] is not None:
                    m, frame["msg"] = frame["msg"], None
                    await client.send_json(m)
                    await asyncio.sleep(0.12)  # ~8 fps cap: enough for typing and captchas, light on mobile data
                    if frame["msg"] is not None or not out.empty():
                        wake.set()

        def push(m):
            out.put_nowait(m)
            wake.set()

        http = ClientSession()
        conn = {"cdp": None, "ws": None, "pump": None, "id": None}

        def on_event(method, p):
            if method == "Page.screencastFrame":
                asyncio.ensure_future(conn["cdp"].fire("Page.screencastFrameAck", sessionId=p["sessionId"]))
                frame["msg"] = {"type": "frame", "data": p["data"], "meta": p.get("metadata")}
                wake.set()
            elif method == "Page.frameNavigated" and not p.get("frame", {}).get("parentId"):
                url = p["frame"].get("url")
                persist(last_url=url)
                push({"type": "url", "url": url})

        async def detach():
            if conn["ws"] is not None:
                try:
                    await conn["cdp"].fire("Page.stopScreencast")
                except Exception:
                    pass
                await conn["ws"].close()
            if conn["pump"] is not None:
                conn["pump"].cancel()
            conn.update(cdp=None, ws=None, pump=None)

        async def attach(target_id=None):
            await detach()
            ps = await pages(http)
            if not ps:
                async with http.put(f"{base}/json/new?about:blank") as r:
                    ps = [await r.json(content_type=None)]
            t = next((x for x in ps if x["id"] == (target_id or app_state["target"])), ps[0])
            app_state["target"] = t["id"]
            async with http.get(f"{base}/json/activate/{t['id']}") as r:
                await r.read()
            ws = await http.ws_connect(t["webSocketDebuggerUrl"], max_msg_size=0)
            cdp = CDP(ws)
            conn.update(cdp=cdp, ws=ws, id=t["id"])
            conn["pump"] = asyncio.ensure_future(cdp.pump(on_event))
            await cdp.call("Page.enable")
            m = await cdp.call("Page.getLayoutMetrics")
            vp = m.get("cssVisualViewport") or m.get("layoutViewport") or {}
            shot = await cdp.call("Page.captureScreenshot", format="jpeg", quality=60)
            frame["msg"] = {"type": "frame", "data": shot["data"], "meta": {
                "deviceWidth": vp.get("clientWidth", 1280), "deviceHeight": vp.get("clientHeight", 900), "offsetTop": 0}}
            wake.set()
            await cdp.call("Page.startScreencast", format="jpeg", quality=60, maxWidth=1600, maxHeight=1600, everyNthFrame=1)
            push({"type": "url", "url": t["url"]})

        async def type_text(text):
            cdp = conn["cdp"]
            if len(text) > 40:  # long pastes: one insertText instead of hundreds of key events
                await cdp.call("Input.insertText", text=text)
                return
            for ch in text:
                vk, code = char_key(ch)
                await cdp.call("Input.dispatchKeyEvent", type="keyDown", key=ch, code=code, text=ch, unmodifiedText=ch, windowsVirtualKeyCode=vk)
                await cdp.call("Input.dispatchKeyEvent", type="keyUp", key=ch, code=code, windowsVirtualKeyCode=vk)

        async def press(key, mod=0):
            cdp = conn["cdp"]
            if key in KEYS:
                vk, code, text = KEYS[key]
            else:
                vk, code = char_key(key[:1])
                text = None
            down = {"type": "keyDown" if text and not mod & 2 else "rawKeyDown", "key": key, "code": code,
                    "windowsVirtualKeyCode": vk, "modifiers": mod}
            if text and not mod & 2:
                down.update(text=text, unmodifiedText=text)
            await cdp.call("Input.dispatchKeyEvent", **down)
            await cdp.call("Input.dispatchKeyEvent", type="keyUp", key=key, code=code, windowsVirtualKeyCode=vk, modifiers=mod)

        snd = asyncio.ensure_future(sender())
        try:
            await attach()
            async for m in client:
                if m.type != WSMsgType.TEXT:
                    break
                app_state["last_seen"] = time.time()
                d = json.loads(m.data)
                t = d.get("type")
                try:
                    if conn["pump"] is None or conn["pump"].done():
                        await attach()
                    cdp = conn["cdp"]
                    if t == "mouse":
                        kw = dict(type=d["ev"], x=float(d["x"]), y=float(d["y"]), modifiers=int(d.get("mod", 0)))
                        if d["ev"] == "mouseMoved":
                            kw.update(button=d.get("button", "none"), buttons=int(d.get("buttons", 0)))
                        else:
                            kw.update(button=d.get("button", "left"), clickCount=int(d.get("clickCount", 1)),
                                      buttons=1 if d["ev"] == "mousePressed" else 0)
                        await cdp.call("Input.dispatchMouseEvent", **kw)
                    elif t == "wheel":
                        await cdp.call("Input.dispatchMouseEvent", type="mouseWheel", x=float(d["x"]), y=float(d["y"]),
                                       deltaX=float(d.get("dx", 0)), deltaY=float(d.get("dy", 0)))
                    elif t == "text":
                        await type_text(str(d.get("text", "")))
                    elif t == "key":
                        await press(str(d.get("key", "")), int(d.get("mod", 0)))
                    elif t == "navigate":
                        url = str(d.get("url", "")).strip()
                        if url:
                            if not re.match(r"^[a-z]+:", url):
                                url = ("https://" + url) if "." in url and " " not in url else \
                                    "https://www.google.com/search?q=" + urllib.parse.quote(url)
                            await cdp.call("Page.navigate", url=url)
                    elif t == "back":
                        await cdp.call("Runtime.evaluate", expression="history.back()")
                    elif t == "reload":
                        await cdp.call("Page.reload")
                    elif t == "tabs":
                        ps = await pages(http)
                        push({"type": "tabs", "tabs": [{"id": x["id"], "title": x.get("title"), "url": x["url"],
                                                        "active": x["id"] == conn["id"]} for x in ps]})
                    elif t == "switch":
                        await attach(d.get("id"))
                    elif t == "newtab":
                        async with http.put(f"{base}/json/new?about:blank") as r:
                            nt = await r.json(content_type=None)
                        await attach(nt["id"])
                    elif t == "mobile":
                        # metrics only: touch emulation would swallow the mouse events the viewer sends
                        if d.get("on"):
                            await cdp.call("Emulation.setDeviceMetricsOverride", width=412, height=860, deviceScaleFactor=2, mobile=True)
                        else:
                            await cdp.call("Emulation.clearDeviceMetricsOverride")
                    elif t == "done":
                        persist(done=True, done_at=time.time())
                        await end(TEXT["r_done"], TEXT["ended_done"])
                except Exception as e:
                    log(f"{t}: {type(e).__name__}: {e}")
                    push({"type": "info", "text": TEXT["failed"]})
        except Exception as e:
            log(f"ws session error: {type(e).__name__}: {e}")
        finally:
            snd.cancel()
            await detach()
            await http.close()
            app_state["last_seen"] = time.time()
        return client

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/s/{token}", claim_page)
    app.router.add_post("/s/{token}", claim)
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)

    async def on_startup(_app):
        asyncio.ensure_future(watchdog())
    app.on_startup.append(on_startup)
    persist(server_pid=os.getpid())
    web.run_app(app, host=LISTEN_HOST, port=st["listen_port"], access_log=None, print=None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start", help="start a session and print the one-time link")
    s.add_argument("--cdp", type=int, default=LIVE_PORT, help="CDP port of the Chrome to share")
    s.add_argument("--url", help="open this URL first")
    s.add_argument("--minutes", type=int, default=30, help="maximum session length")
    s.add_argument("--open-minutes", type=int, default=10, help="how long the link can be opened")
    s.add_argument("--probe", type=int, default=12, help="seconds to wait for the public URL to answer")
    s.add_argument("--json", action="store_true")
    w = sub.add_parser("wait", help="block until Done or the session ends")
    w.add_argument("--timeout", type=int, default=600)
    sub.add_parser("status")
    p = sub.add_parser("stop")
    p.add_argument("--chrome", action="store_true", help="also kill the dedicated Chrome")
    sub.add_parser("serve")
    a = ap.parse_args()
    {"start": cmd_start, "status": cmd_status, "wait": cmd_wait, "stop": cmd_stop, "serve": lambda _a: serve()}[a.cmd](a)


if __name__ == "__main__":
    main()
