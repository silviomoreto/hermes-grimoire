#!/usr/bin/env python3
"""Drive your own WhatsApp Web through a dedicated, persistent headless Chrome (CDP).

  wa.py status                       -> logged_in | logged_out | loading
  wa.py login-code <phone digits>    -> prints the 8-char "link with phone number" code
  wa.py search "<query>"             -> chat titles matching the query (primes the search box)
  wa.py read "<chat name>" [n]       -> last n rows of that chat (default 15), labeled ME/THEM
  wa.py send "<chat name>" "<text>"  -> sends ONLY if the exact text lands in the box
  wa.py send-image "<chat>" <path> "<caption>" [--dry]
  wa.py js "<expr>"                  -> debug eval
  wa.py shot <path>                  -> screenshot

Env: WA_CDP_PORT (default 9333); for login-code: WA_COUNTRY (text typed in the country picker,
default "Brasil"), WA_COUNTRY_RE (regex of the list item, default "(Brasil|Brazil).*\\+55"),
WA_DIAL_CODE (default "+55"). Start the browser first with wa-browser.sh (idempotent).
Only send what the user approved word for word.
"""
import asyncio, base64, json, os, sys, time, urllib.request
import websockets

PORT = int(os.environ.get("WA_CDP_PORT", "9333"))
COUNTRY = os.environ.get("WA_COUNTRY", "Brasil")
COUNTRY_RE = os.environ.get("WA_COUNTRY_RE", r"(Brasil|Brazil).*\+55")
DIAL_CODE = os.environ.get("WA_DIAL_CODE", "+55")


def page_ws():
    for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list")):
        if t["type"] == "page" and "whatsapp" in t["url"]:
            return t["webSocketDebuggerUrl"]
    t = json.load(urllib.request.urlopen(urllib.request.Request(
        f"http://127.0.0.1:{PORT}/json/new?https://web.whatsapp.com/", method="PUT")))
    return t["webSocketDebuggerUrl"]


class Page:
    def __init__(self, ws):
        self.ws, self.i = ws, 0

    async def send(self, method, **params):
        self.i += 1
        mid = self.i
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            m = json.loads(await self.ws.recv())
            if m.get("id") == mid:
                if "error" in m:
                    raise RuntimeError(m["error"])
                return m.get("result", {})

    async def js(self, expr):
        r = await self.send("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    async def type(self, text):
        await self.send("Input.insertText", text=text)

    async def key(self, key, code=None, vk=None):
        for t in ("keyDown", "keyUp"):
            params = {"type": t, "key": key, "code": code or key, "windowsVirtualKeyCode": vk or 0}
            if len(key) == 1 and t == "keyDown":
                params["text"] = key
            await self.send("Input.dispatchKeyEvent", **params)


async def status(p):
    t = await p.js("document.body ? document.body.innerText.slice(0,400) : ''") or ""
    if any(s in t for s in ("Escaneie", "Scan to", "Entrar com número", "Log in with phone", "Insira o código", "Enter code")):
        return "logged_out"
    if await p.js("!!document.querySelector('#pane-side, [aria-label=\"Lista de conversas\"], [aria-label=\"Chat list\"]')"):
        return "logged_in"
    return "loading"


CLICK_TEXT = """((re)=>{const r=new RegExp(re,'i');const e=[...document.querySelectorAll('div[role=button],button,span,a')]
.filter(x=>x.innerText&&r.test(x.innerText.trim())&&x.innerText.length<60);if(!e.length)return false;e[e.length-1].click();return true})"""


async def login_code(p, digits):
    await p.send("Page.navigate", url="https://web.whatsapp.com/")
    await asyncio.sleep(12)
    if await status(p) == "logged_in":
        return "already logged in"
    await p.js(CLICK_TEXT + "('^(Entrar com número de telefone|Log in with phone number)$')")
    await asyncio.sleep(3)
    # country selector: the button showing the current country, then type WA_COUNTRY and pick it
    await p.js("""(()=>{const skip=/^(Next|Avançar|Log in with QR code|Conectar com o QR code|Get started|Começar|Terms|Termos)/;const b=[...document.querySelectorAll('div[role=button],button')].find(x=>x.innerText.trim()&&!skip.test(x.innerText.trim())&&x.innerText.length<40);b&&b.click()})()""")
    await asyncio.sleep(1.5)
    await p.type(COUNTRY)
    await asyncio.sleep(1.5)
    await p.js(f"""(()=>{{const re=new RegExp({json.dumps(COUNTRY_RE)});const e=[...document.querySelectorAll('li,div[role=button],button,span')].find(x=>re.test(x.innerText.trim().replace(/\\n/g,' '))&&x.innerText.length<40);e&&e.click();return !!e}})()""")
    await asyncio.sleep(1.5)
    await p.js("(()=>{const i=document.querySelector('input[type=text]');i.focus();i.setSelectionRange(i.value.length,i.value.length)})()")
    for ch in digits:
        await p.key(ch)
        await asyncio.sleep(0.05)
    val = await p.js("document.querySelector('input[type=text]').value")
    if not (val or "").replace(" ", "").startswith(DIAL_CODE):
        return f"failed to fill the phone number: {val!r}"
    await p.js(CLICK_TEXT + "('^(Avançar|Next)$')")
    await asyncio.sleep(7)
    code = await p.js("""(()=>{const t=document.body.innerText;const m=t.replace(/\\n/g,'').match(/[A-Z0-9]{4}-[A-Z0-9]{4}/g);return m?m[m.length-1]:t.slice(0,300)})()""")
    return code


async def open_chat(p, name):
    hdr = await p.js("document.querySelector('#main header')?.innerText||''")
    if name in (hdr or ""):
        return True
    # dismiss "What's new" / other modal dialogs
    await p.js("""(()=>{const b=[...document.querySelectorAll('[role=dialog] button, [role=dialog] div[role=button]')].find(x=>/^(Continue|Continuar|OK|Fechar|Close)$/.test(x.innerText.trim()));b&&b.click()})()""")
    await asyncio.sleep(1)
    locate = f"""(()=>{{const n={json.dumps(name)};const s=[...document.querySelectorAll('#pane-side span[title]')].find(x=>x.getAttribute('title')===n);
      if(!s)return null;const r=s.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]}})()"""
    xy = await p.js(locate)
    if not xy:
        await p.js("""(()=>{const b=document.querySelector('#side input, #side [contenteditable=true]');b&&b.focus()})()""")
        await p.send("Input.dispatchKeyEvent", type="keyDown", key="a", code="KeyA", windowsVirtualKeyCode=65, modifiers=2)
        await p.send("Input.dispatchKeyEvent", type="keyUp", key="a", code="KeyA", windowsVirtualKeyCode=65, modifiers=2)
        for t in ("keyDown", "keyUp"):
            await p.send("Input.dispatchKeyEvent", type=t, key="Backspace", code="Backspace", windowsVirtualKeyCode=8)
        await p.type(name)
        await asyncio.sleep(4)
        xy = await p.js(locate)
        if not xy:  # search sometimes ignores the first input burst: retry once
            await p.js("""(()=>{const b=document.querySelector('#side input, #side [contenteditable=true]');b&&b.focus()})()""")
            await p.type(" ")
            for t in ("keyDown", "keyUp"):
                await p.send("Input.dispatchKeyEvent", type=t, key="Backspace", code="Backspace", windowsVirtualKeyCode=8)
            await asyncio.sleep(3)
            xy = await p.js(locate)
    if xy:
        for t in ("mousePressed", "mouseReleased"):
            await p.send("Input.dispatchMouseEvent", type=t, x=xy[0], y=xy[1], button="left", clickCount=1)
    await asyncio.sleep(2.5)
    hdr = await p.js("document.querySelector('#main header')?.innerText||''")
    return name in (hdr or "")


async def search(p, query):
    """Type the query in the chat search box and return the matching chat titles."""
    await p.js("""(()=>{const b=document.querySelector('#side input, #side [contenteditable=true]');b&&b.focus()})()""")
    for t in ("keyDown", "keyUp"):
        await p.send("Input.dispatchKeyEvent", type=t, key="a", code="KeyA", windowsVirtualKeyCode=65, modifiers=2)
    for t in ("keyDown", "keyUp"):
        await p.send("Input.dispatchKeyEvent", type=t, key="Backspace", code="Backspace", windowsVirtualKeyCode=8)
    await p.type(query)
    await asyncio.sleep(5)
    return await p.js("[...document.querySelectorAll('#pane-side span[title]')].map(x=>x.getAttribute('title')).filter(t=>t&&t.length<80).slice(0,25)")


async def read(p, name, n):
    if not await open_chat(p, name):
        return f"chat '{name}' not found"
    return await p.js(f"""[...document.querySelectorAll('#main [role=row]')].slice(-{n}).map(r=>((()=>{{const e=(r.querySelector('.copyable-text')||r).getBoundingClientRect();const m=document.querySelector('#main').getBoundingClientRect();return (m.right-e.right)<(e.left-m.left)?'ME: ':'THEM: '}})())+r.innerText.replace(/\\n/g,' | '))""")


async def send(p, name, text):
    if not await open_chat(p, name):
        return f"chat '{name}' not found; nothing sent"
    await p.js("document.querySelector('#main footer div[contenteditable=true]').focus()")
    await p.type(text)
    await asyncio.sleep(0.8)
    typed = await p.js("document.querySelector('#main footer div[contenteditable=true]').innerText")
    if typed.strip() != text.strip():
        return f"text in the box differs; NOT sent: {typed!r}"
    await p.send("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13)
    await p.send("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13)
    await asyncio.sleep(2.5)
    return await p.js("[...document.querySelectorAll('#main [role=row]')].slice(-1).map(r=>r.innerText.replace(/\\n/g,' | '))")


async def click_xy(p, sel_js):
    xy = await p.js(sel_js)
    if not xy:
        return False
    for t in ("mousePressed", "mouseReleased"):
        await p.send("Input.dispatchMouseEvent", type=t, x=xy[0], y=xy[1], button="left", clickCount=1)
    return True


async def clear_footer(p):
    """WhatsApp keeps a discarded caption as the chat draft: wipe it."""
    await p.js("document.querySelector('#main footer div[contenteditable=true]')?.focus()")
    await p.send("Input.dispatchKeyEvent", type="keyDown", key="a", code="KeyA", windowsVirtualKeyCode=65, modifiers=2)
    await p.send("Input.dispatchKeyEvent", type="keyUp", key="a", code="KeyA", windowsVirtualKeyCode=65, modifiers=2)
    for t in ("keyDown", "keyUp"):
        await p.send("Input.dispatchKeyEvent", type=t, key="Backspace", code="Backspace", windowsVirtualKeyCode=8)
    await asyncio.sleep(0.5)


async def discard(p):
    await click_xy(p, """(()=>{const b=[...document.querySelectorAll('[aria-label="Close"],[aria-label="Fechar"]')].find(x=>x.offsetParent&&!x.closest('#side'));if(!b)return null;const r=b.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()""")
    await asyncio.sleep(1)
    await click_xy(p, """(()=>{const b=[...document.querySelectorAll('button,div[role=button]')].find(x=>/^(Discard|Descartar)$/.test(x.innerText.trim()));if(!b)return null;const r=b.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()""")
    await asyncio.sleep(1)
    await clear_footer(p)


async def send_image(p, name, path, caption, dry=False):
    if not await open_chat(p, name):
        return f"chat '{name}' not found; nothing sent"
    ok = await click_xy(p, """(()=>{const b=document.querySelector('#main footer [aria-label="Attach"],#main footer [aria-label="Anexar"],#main footer [title="Attach"],#main footer [title="Anexar"]');
      if(!b)return null;const r=b.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()""")
    if not ok:
        return "attach button not found; nothing sent"
    await asyncio.sleep(1.5)
    await p.send("Page.enable")
    await p.send("Page.setInterceptFileChooserDialog", enabled=True)
    ok = await click_xy(p, """(()=>{const b=[...document.querySelectorAll('li,[role=menuitem],[role=button],div')].find(x=>/^(Photos & videos|Fotos e vídeos)$/.test(x.innerText.trim()));if(!b)return null;const r=b.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()""")
    if not ok:
        return "'Photos & videos' item not found; nothing sent"
    backend = None
    t0 = time.time()
    while time.time() - t0 < 20 and backend is None:
        try:
            m = json.loads(await asyncio.wait_for(p.ws.recv(), timeout=20))
        except asyncio.TimeoutError:
            break
        if m.get("method") == "Page.fileChooserOpened":
            backend = m["params"]["backendNodeId"]
    await p.send("Page.setInterceptFileChooserDialog", enabled=False)
    if backend is None:
        return "file chooser did not open; nothing sent"
    await p.send("DOM.setFileInputFiles", backendNodeId=backend, files=[path])
    await asyncio.sleep(4)
    if caption:
        got = await p.js("""(()=>{const c=[...document.querySelectorAll('div[contenteditable=true]')].find(x=>!x.closest('#main footer')&&!x.closest('#side'));if(!c)return false;c.focus();return true})()""")
        if not got:
            await discard(p)
            return "caption field not found; nothing sent"
        await p.type(caption)
        await asyncio.sleep(1)
    preview = await p.js("""!![...document.querySelectorAll('[aria-label]')].find(e=>/^(Send|Enviar)/.test(e.getAttribute('aria-label'))&&!e.closest('#main footer'))""")
    if dry:
        footer = await p.js("document.querySelector('#main footer div[contenteditable=true]')?.innerText.trim()")
        await discard(p)
        return {"dry_run": True, "preview_with_send_button": preview, "footer_text_leak": footer}
    if not preview:
        return "preview did not open; nothing sent"
    await click_xy(p, """(()=>{const b=[...document.querySelectorAll('[aria-label]')].find(e=>/^(Send|Enviar)/.test(e.getAttribute('aria-label'))&&!e.closest('#main footer'));const r=b.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()""")
    await asyncio.sleep(5)
    return await p.js("[...document.querySelectorAll('#main [role=row]')].slice(-1).map(r=>r.innerText.replace(/\\n/g,' | ')+(r.querySelector('img')?' [image]':''))")


async def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, *args = sys.argv[1:]
    async with websockets.connect(page_ws(), max_size=50_000_000) as ws:
        p = Page(ws)
        await p.send("Page.bringToFront")
        if cmd == "status":
            out = await status(p)
        elif cmd == "login-code":
            out = await login_code(p, args[0])
        elif cmd == "search":
            out = await search(p, args[0])
        elif cmd == "read":
            out = await read(p, args[0], int(args[1]) if len(args) > 1 else 15)
        elif cmd == "send":
            out = await send(p, args[0], args[1])
        elif cmd == "send-image":
            out = await send_image(p, args[0], args[1], args[2] if len(args) > 2 else "", dry=len(args) > 3 and args[3] == "--dry")
        elif cmd == "js":
            out = await p.js(args[0])
        elif cmd == "shot":
            r = await p.send("Page.captureScreenshot", format="png")
            open(args[0], "wb").write(base64.b64decode(r["data"]))
            out = args[0]
        else:
            out = __doc__
    print(json.dumps(out, ensure_ascii=False) if not isinstance(out, str) else out)


asyncio.run(main())
