# Helpers for Angular Material forms driven through browser_exec.
# Load at the start of each browser_exec call:
#   exec(open('/path/to/form_helpers.py').read())
# They rely on js / cdp / click_at_xy / fill_input from the browser_exec globals,
# which is why they are exec'd instead of imported.
import time, json


def mat_select(sel, text, exact=True):
    """Open a mat-select (or any dropdown) by clicking its centre, then click the matching mat-option."""
    js(f"document.querySelector('{sel}').scrollIntoView({{block:'center'}})"); time.sleep(0.5)
    b = json.loads(js(f"JSON.stringify(document.querySelector('{sel}').getBoundingClientRect())"))
    click_at_xy(b['x'] + b['width'] / 2, b['y'] + b['height'] / 2); time.sleep(1.2)
    r = js("""(()=>{const t=%s; const ex=%s; const o=[...document.querySelectorAll('mat-option')].find(o=>ex? o.innerText.trim()===t : o.innerText.trim().startsWith(t)); if(!o) return 'notfound:'+[...document.querySelectorAll('mat-option')].slice(0,6).map(o=>o.innerText.trim()).join('|'); o.scrollIntoView({block:'center'}); o.click(); return 'ok'})()""" % (json.dumps(text), 'true' if exact else 'false'))
    time.sleep(0.8)
    return r


def type_autocomplete(input_id, text, wait=3.5):
    """Type into an autocomplete input as real typing and return the option texts shown."""
    js(f"(()=>{{const i=document.getElementById('{input_id}'); i.scrollIntoView({{block:'center'}}); i.focus(); i.select()}})()")
    time.sleep(0.3)
    cdp('Input.insertText', text=text)
    time.sleep(wait)
    return json.loads(js("JSON.stringify([...document.querySelectorAll('mat-option')].map(o=>o.innerText.trim().replace(/\\s+/g,' ')).slice(0,10))"))


def pick_option(idx):
    js(f"document.querySelectorAll('mat-option')[{idx}].click()"); time.sleep(1.5)


def esc():
    """Close an open option list. Never call it with no list open: it closes the dialog."""
    cdp('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    cdp('Input.dispatchKeyEvent', type='keyUp', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    time.sleep(0.8)


def form_values():
    """id=value for every field in the open dialog, to read back before saving."""
    return js("""JSON.stringify([...document.querySelectorAll('mat-dialog-container input, mat-dialog-container mat-select, mat-dialog-container textarea')].map(e=>(e.id+'='+(e.value!==undefined?e.value:e.innerText||'').toString().slice(0,70))))""")


def save_dialog(label='Save changes'):
    """Click the dialog button whose text starts with label; report whether the dialog closed."""
    r = js("""(()=>{const b=[...document.querySelectorAll('mat-dialog-container button')].find(b=>b.innerText.trim().startsWith(%s)); if(!b) return 'nobtn'; b.click(); return 'clicked'})()""" % json.dumps(label))
    time.sleep(5)
    if js("!!document.querySelector('mat-dialog-container')"):
        return r + ' | DIALOG OPEN: ' + js("document.querySelector('mat-dialog-container').innerText.slice(0,400)")
    return r + ' | closed'
