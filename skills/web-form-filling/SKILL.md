---
name: web-form-filling
description: "Use when filling SPA web forms through browser_exec."
---

# Filling forms on SPA sites with browser_exec

Enter data through a logged-in site's own UI: research profiles (ORCID), portals, admin panels. The loop: log in, map the form, fill, read the values back, save, check the dialog closed, verify from an independent source.

> **Safety first.** Editing a public profile is publishing. Show the user what will be saved and get a clear go before saving. Never put an unconfirmed number or claim in a public field: ask, or leave it out and say so. Never solve a CAPTCHA or type a password yourself: use the vault, or ask the user for a logged-in session.

## When to Use
- Several records or fields to enter through a web UI (no write API, or the API needs credentials you don't have).
- Not for read-only scraping: try `curl` or a public JSON endpoint first.
- Not for sites behind CAPTCHA: ask the user to log in and reuse that session.

## Setup
- Hermes `browser_exec` tool (helpers `js`, `cdp`, `click_at_xy`, `fill_input`, `capture_screenshot`). `browser_vault` is optional, for logins.
- `scripts/form_helpers.py`: copy it into the browser_exec workspace (`$BH_AGENT_WORKSPACE`) under any name except `agent_helpers.py`.
- The helpers and selectors target **Angular Material** (`mat-select`, `mat-option`, `mat-dialog-container`), used by many sites, ORCID included. On React or other UI kits the procedure is the same; swap the selectors (look for `role="listbox"`, `role="option"`, `role="dialog"`).

## Procedure
1. **Log in through the vault.** `browser_vault list` → open the login page in the DEFAULT browser_exec session (the vault fills that tab) → type the identifier → `browser_vault fill <handle>` → read back that both fields have a value → click submit → check that `location.href` left the sign-in page. Sessions on these sites expire fast: open the record page first and log in again if it redirects to sign-in.
2. **Widen the viewport before touching dialogs:** `cdp('Emulation.setDeviceMetricsOverride', width=1280, height=1000, deviceScaleFactor=1, mobile=False)`. In a small viewport, dropdowns and menus open off-screen or behind the dialog. Reset at the end with `cdp('Emulation.clearDeviceMetricsOverride')`.
3. **Map before filling:** list `input, textarea, mat-select` inside `mat-dialog-container` with `id` and `formcontrolname`. Select ids are dynamic (`mat-select-84`), so build a formcontrolname→id map in the same call that uses it.
4. **Fill:**
   - Text: `fill_input('#id', text)` for plain inputs. For login fields and inputs that keep a stale or empty value, focus and select, then `cdp('Input.insertText', text=...)`: the framework sees it as real typing.
   - Dropdown: click the element's bounding-box centre with `click_at_xy`, then click the option whose trimmed text matches (`mat_select`). Nested menus (type → category → item) need a screenshot to find the coordinates.
   - Autocomplete (organization or registry pickers): insertText, wait ~3 s, read the option list, pick by substring (`type_autocomplete` + `pick_option`). If nothing fits, keep the free text and fill the dependent fields (city, region, country) yourself.
   - **Press Escape only when an option list is open.** With no list open, Escape closes the whole dialog and the form is lost.
   - File upload: `DOM.getDocument` → `DOM.querySelector` on `input[type=file]` → `DOM.setFileInputFiles(nodeId=..., files=[path])`. The path must exist on the machine running the browser.
5. **Read back before saving:** print every field (`form_values`) and check it, then click the save button by its text (`save_dialog`). After saving, the dialog must be gone. If it is still open, its text holds the validation error.
6. **Verify independently:** reread the section on the page or, better, a public API or JSON export of the record. Report only what that check shows.

## Reusing helpers across calls
- browser_exec starts a fresh interpreter on every call. Functions in the workspace `agent_helpers.py` are imported as a module, so they cannot call `js`/`cdp`/`click_at_xy` (NameError), and proxying them through `sys.modules['__main__']` recurses forever. Keep the helpers in another file and start each call with `exec(open('<workspace>/form_helpers.py').read())`.
- Batch several records per call: a list of dicts and a loop that saves only when the read-back looks right. Stop on the first odd result instead of pushing on.

## Pitfalls
- **Bulk import beats typing.** When the site imports a standard file (BibTeX, CSV, vCard), generate the file and upload it. Then check the TYPE each record got: importers map unusual entry types to the wrong category (a BibTeX `@mastersthesis` can land as a "supervised student publication"). Add those few through the site's own ID lookup (DOI, ISBN) instead.
- **Metadata from the source, not from memory.** For papers, `curl -LH "Accept: application/x-bibtex" https://doi.org/<doi>` returns the official BibTeX.
- **Autocomplete lists lie by omission.** A company that is not in the registry returns unrelated options (other organizations with a similar word). Never pick one just because it is first.
