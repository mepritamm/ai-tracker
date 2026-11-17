# Terminal theme: black by default everywhere, switchable only from Config

Status: PLAN (no code written). Worktree `.claude/worktrees/term-black-default`, branch
`term-black-default`, base `418f132`.

## 1. Contract (verbatim)

> "make it mandatory across the entire app, all the terminal window across the entire app should be black by default, and wont switch unless/until somebody does it from the new config setting."

Context: the "Claude Code login" dialog (Config, then Log in / Switch account) showed its
embedded xterm terminal in the light beige app theme.

| # | Clause | Discharged by |
|---|---|---|
| C1 | Applies to *every* terminal surface in the app | §2 inventory; §4 one CSS scope covers all 3 `.vttermwrap` creation sites + modal body + full-tab + command-runner output |
| C2 | Black **by default** | `TERM_THEME` default `"black"`; the CSS selector is `html:not([data-term-theme="app"])`, so a missing or garbled attribute still renders black |
| C3 | Independent of the app's light/dark theme ("mandatory") | the token block is declared *on* the terminal elements, so neither `html.light` nor the CR theme sync nor CR's inline `setTheme` can reach the terminal while black |
| C4 | Won't switch unless someone changes **the new Config setting** | the per-terminal flipper (`.vtthemebtn`) is hidden while black (§4.4); `themechange` repaints use the black tokens; only `TERM_THEME` (Config, then Terminal) changes it |
| C5 | A **new** Config setting | `TERM_THEME` row at the top of Config, then Terminal (§3.4) |

## 2. Every terminal surface, and how it is themed today

All renderers are built by the same two classes in `aitracker/web/ext_vt.js`: grid
`Terminal(container, ttyId, rendererSwitch)` (`ext_vt.js:710`) and `XtermTerminal(...)`
(`ext_vt.js:1746`). Each constructor appends `buildToolbar()` (`ext_vt.js:515`) and a `.vtpane` to the
`container` it is given. Every construction site passes a **`.vttermwrap`** div as that container.

| Surface | Mount | Container chain | Theming today |
|---|---|---|---|
| Pop-up terminal modal (classic and CR "Open terminal") | `openVT`, wrap built at `ext_vt.js:3107-3110`; switch at `switchActiveRenderer` `ext_vt.js:2896-2904` | `#vtmodal .modal.vtmodal > .mb.vtmb` (`ext_vt.js:2093`) > `.vttermwrap` + `.vtctxbar` + notice banners | inherits `--app/--text/...` from `:root` / `html.light` (`app.css:1-2`) |
| Full-tab terminal (`?tty=` link, "New tab", ExtLaunch `openNewTab`) | `bootStandalone` `ext_vt.js:4095`, `mount.classList.add("vtfull")` `:4141`, wrap `:4252`, `mountRenderer` `:4184` | `#ext_vt.vtfull` > `.vttermwrap` + `.vtctxbar` + `.vtfullstatus` | same root tokens; `#ext_vt.vtfull{background:var(--app)}` `ext_vt.css:505` |
| Control Room inline PTY pane | `ext_cr_term.js:355` `_attachEngine`, then `ExtVT.mountInto` `ext_vt.js:3743`, wrap `:3749-3751` | CR container > `.vttermwrap` | forced dark: `DARK_PANE_THEME = {#12100E,#E4D8CA,#E5CB79}` `ext_cr_term.js:374`, pushed via `handle.setTheme()` at `:540` and `:954`. That writes inline `--app/--text/--ring2` on the CR container only (`ext_vt.js:3802-3809`); the ANSI tokens (`--dim/--red/...`) still come from `html.light` |
| **Claude Code login dialog** (the screenshot) | `renderClaudeLogin` `ext_cr_dialogs.js:1685`, `ExtVT.mountInto(termEl, ...)` `:1702` | `.cr-dialog-login .cr-login-term` (`ext_cr_dialogs.css:661-662`) > `.vttermwrap` | plain root tokens. CR's theme sync (`ext_cr_boot.js:132` `syncClassicTheme` → `setTheme`) puts `html.light` on, so the dialog renders beige. **This is the bug.** |
| Embedded command runner output (Tier 2, `#ext_run`) | `ext_run.js:9` | `.runout` (`ext_run.css:9`) | root tokens + `--rn-*` (`ext_run.css:25-36`). It renders SGR output, so it is a terminal-like surface. Included, see Decision D3 |

Colour readers:
- Grid: pure CSS. `.vtpane{background:var(--app)}` `ext_vt.css:94`, `.vtrow{color:var(--text)}` `:106`,
  the SGR classes `:435-459` (`--dim/--red/--green/--amber/--blue/--violet/--ring2/--head`, `--*-bg`, `--vt-*-bg`),
  `.vttoolbar` `:231`, `.vtzoombtn` `:239`, `.vtctxbar` (around `:300`).
- xterm: JS object from `_xtermTheme(el)` `ext_vt.js:1734-1741`, which reads `--app/--text/--ring2` from
  `getComputedStyle(el || documentElement)`. It is read in three places:
  1. `_build` `ext_vt.js:1833`: `_xtermTheme(this.container)`. The container is the `.vttermwrap`.
  2. `_onThemeChange` `ext_vt.js:1810`: `_xtermTheme()`, which reads the **document root**. Its literal is pinned by
     `tests/test_term_vt_client.py:2046`.
  3. `mountInto.setTheme` `ext_vt.js:3808`: `_xtermTheme(container)`. This is the **caller's** container, not the wrap.
- The per-terminal theme flipper `.vtthemebtn` (`ext_vt.js:518-569`) calls the global `toggleTheme()`.
  That flips the **app** theme and, through `themechange`, the terminal colours too.
- The CR overlay "Theme" button (`ext_cr_term.js:189`, `_cycleTheme` `:976`) cycles the CR/app theme. Its pane is already
  documented as "never light-themes" and stays as it is.
- Not a terminal: `app.js:990` `_mermaidThemeVars` is the Mermaid diagram theme. It only mirrors the idea. Out of scope.

## 3. Server-side setting: `TERM_THEME`

### 3.1 Values (minimal useful set)
- `"black"` (default): every terminal uses one fixed dark palette, whatever the app theme is.
- `"app"`: follow the app theme. This is exactly today's behaviour, so nothing is lost.

A fixed `"light"` option was not requested. It would also need a second hand-tuned SGR palette, so it is left out.

### 3.2 `aitracker/config.py`. Reuses the existing settings seam exactly (ICON_STYLE / HEADER_LINE shape: no env var, config.json > default)
- `EDITABLE` (`config.py:225`): append `"TERM_THEME"`.
- Not in `RESTART_REQUIRED` (`:236`). It applies live.
- `VALIDATORS` (`:300`): `"TERM_THEME": _v_enum(("black", "app")),`
- New resolver next to `resolve_header_line` (`:490`):
  ```python
  def resolve_term_theme(overrides):
      """Terminal colours: "black" (default; every terminal, whatever the app theme) or "app"
      (follow the app's light/dark). No env var -- config.json > built-in "black"."""
      v = overrides.get("TERM_THEME")
      return v if v in ("black", "app") else "black"
  ```
- `_RESOLVERS` (`:581`): `"TERM_THEME": resolve_term_theme,`
- `_PLAIN_ATTR_KEYS` (`:605`): append `"TERM_THEME"`. `page.py` reads `config.TERM_THEME` at page-build time, so it
  needs the plain attribute that `apply_overrides()` repoints. That runs at startup (`server.py:1149`) and on every
  GET/POST `/api/config` (`server.py:528`, `:798`).
- Seed, with the other globals (`:614-625`): `TERM_THEME = resolve_term_theme({})`
- No `server.py` change. POST `/api/config` validates against `VALIDATORS[key]`, writes config.json and calls
  `apply_overrides`. GET returns `snapshot()`, which covers every `EDITABLE` key automatically.

### 3.3 How the SPA receives it: `page.build_page()` substitution (the LIVE_WINDOW precedent), not a fetch
CSS needs the value **before the first paint**, and the full-tab terminal is its own page load. So the server writes it
straight into the HTML that `GET /` serves. `GET /` calls `build_page()` on every request (`server.py:447`).
- `aitracker/web/index.html:1`: `<!doctype html><html><head>` becomes `<!doctype html><html data-term-theme="black"><head>`.
  An unsubstituted file is still valid and still black.
- `aitracker/page.py`:
  ```python
  TERM_THEME_MARK = '<html data-term-theme="black">'
  ...
  html = read("index.html").replace(TERM_THEME_MARK, '<html data-term-theme="%s">' % config.TERM_THEME)
  ```
  There is no injection surface: the value is enum-validated and the resolver falls back to `"black"`.
- Other already-open tabs pick up a change on reload. That matches the documented LIVE_WINDOW behaviour
  (`ext_cr_dialogs.js:1929` subtitle). The tab that changes the setting applies it live (§5).

### 3.4 Config panel row: `aitracker/web/ext_cr_dialogs.js`
- `_ENVCHIP` (`:860`): add `TERM_THEME: null,   // no env var -- config.json > built-in default`.
- In `renderSection()` under `active === 'Terminal'` (`:1951`), add it as the **first** row, above "Terminal renderer".
  It uses the existing `serverRow` (`:1813`) with the `onFail` revert, the same idiom as the Icon style row (`:1854-1873`):
  ```js
  function revertTermTheme() {
    if (typeof window.applyTermTheme !== 'function') return;
    window.applyTermTheme((srv.cfg && srv.cfg.TERM_THEME && srv.cfg.TERM_THEME.value) || 'black');
  }
  body.appendChild(serverRow('Terminal colours', 'TERM_THEME',
    'Every terminal in the app (pop-up, full tab, Control Room pane, login window, command output). Black stays black in light and dark theme; Follow app theme uses the app\'s light/dark colours.',
    function (value, onCommit) {
      return segmented([['black', 'Black'], ['app', 'Follow app theme']], value || 'black', function (v) {
        if (typeof window.applyTermTheme === 'function') window.applyTermTheme(v);   // live preview
        onCommit(v);
      });
    }, revertTermTheme));
  ```
- `TERMINAL_REFERENCE` (`:653`): change the text to
  `'Renderer control — xterm (default) or grid, per terminal. Colours: Config → Terminal → Terminal colours (theme toggle shows only with Follow app theme).'`

## 4. Client: ONE place decides terminal colours

### 4.1 The black palette = the app's existing DARK palette, declared once on terminal elements (`aitracker/web/ext_vt.css`)
The palette is the token set from `app.css:1` (`:root`), copied verbatim, plus the dark `--vt-*` (`ext_vt.css:419-424`)
and `--rn-*` (`ext_run.css:25-30`) values. Why this palette:
- It is exactly what the terminal looks like today for a dark-theme user.
- Every SGR class in ext_vt.css and ext_run.css was tuned against it.
- It is near-black: `--app:#0c0f15` background, `--text:#e6edf3` foreground (~16:1 contrast), cursor `--ring2:#29d398`.

`DARK_PANE_THEME` (`#12100E`) is not reused. It only covers 3 of the ~25 tokens a terminal uses, and it would leave the
ANSI colours light-tuned. Append to `ext_vt.css`, after the `html.light{--vt-*}` block (`:425-430`):
```css
/* TERM_THEME (config.py; served as <html data-term-theme>, page.py). Default "black": every terminal
   surface re-declares the app's DARK tokens (copied verbatim from app.css's :root line 1 + the dark
   --vt-/--rn- tints) ON ITSELF, so html.light, the Control Room theme sync and mountInto's inline
   setTheme() on a parent can never reach it. Only TERM_THEME="app" turns this off. Keep in sync with
   app.css line 1 -- tests/test_term_theme.py pins the copy. */
html:not([data-term-theme="app"]) .vttermwrap,
html:not([data-term-theme="app"]) .vtmb,
html:not([data-term-theme="app"]) #ext_vt.vtfull,
html:not([data-term-theme="app"]) .runout {
  --app:#0c0f15;--side:#0a0d12;--card:#0e121a; /* ...every declaration of app.css:1, verbatim... */
  --vt-black-bg:rgba(107,117,133,.14);--vt-violet-bg:rgba(167,139,250,.14);--vt-cyan-bg:rgba(41,211,152,.14);--vt-white-bg:rgba(201,212,224,.14);
  --rn-black-bg:rgba(107,117,133,.14);--rn-violet-bg:rgba(167,139,250,.14);--rn-cyan-bg:rgba(41,211,152,.14);--rn-white-bg:rgba(201,212,224,.14);
  color-scheme: dark;
}
html:not([data-term-theme="app"]) .vtthemebtn { display: none; }
```
Why each scope is there:
- `.vttermwrap`: toolbar and pane, for both renderers, in all 3 mounts (modal, full tab, mountInto). This also covers
  the CR pane and the login dialog.
- `.vtmb`: the modal body. It also holds the `.vtctxbar` and notice banners under the pane.
- `#ext_vt.vtfull`: the whole full-tab page (ctxbar, `.vtfullstatus`).
- `.runout`: the command-runner output.

Why it beats CR's inline override: a custom property *declared on an element* always wins over the value it would
*inherit* from its parent. `ext_cr_term.js` writes its inline `--app` on the parent container, so with this rule the
wrap's own value wins. `ext_cr_term.js` needs no change. In `"app"` mode the rule is off, and CR's `DARK_PANE_THEME`
keeps working exactly as today.

### 4.2 xterm reads the same block: `aitracker/web/ext_vt.js`, no change to `_xtermTheme` itself
- `_build` (`:1833`) already reads `this.container` (the wrap), so it inherits the block with no change.
- `_onThemeChange` (`:1810`): change it to
  `this._onThemeChange = function () { if (self.term) self.term.options.theme = _xtermTheme(self.container); };`
  Without this, an app light/dark flip re-reads the document root and turns a black xterm beige. That is clause C3/C4's
  real bug path.
  In `"app"` mode the result is identical for the modal and the full tab, because the wrap inherits from the root. For
  the CR pane it now keeps `DARK_PANE_THEME` instead of losing it. That closes the edge case the comment at `:1801-1809`
  already admits. Rewrite that comment in one sentence.
- `mountInto.setTheme` (`:3808`): `_xtermTheme(container)` becomes `_xtermTheme(wrap)`. Then xterm and grid both read the
  wrap: black when black, and the CR inline override in "app" mode, as today.

### 4.3 Live switch: `aitracker/web/app.js` + `ext_vt.js`
- `app.js`, right after `window.applyIconStyle=applyIconStyle;` (`:171`):
  ```js
  // Terminal colours (config TERM_THEME, served pre-paint as <html data-term-theme>). Only the Config row calls this.
  function applyTermTheme(v){const t=v==="app"?"app":"black";document.documentElement.setAttribute("data-term-theme",t);document.dispatchEvent(new CustomEvent("termthemechange",{detail:{termTheme:t}}));}
  window.applyTermTheme=applyTermTheme;
  ```
  It uses a new event rather than `themechange`. `ext_cr_boot.js:190` listens for `themechange` and syncs the CR theme
  preference from `detail.theme`, so a terminal-only change sent on that event would corrupt it. A test also pins that
  app.js has exactly 1 `CustomEvent("themechange"` (`test_term_vt_client.py:2010`).
- `ext_vt.js` XtermTerminal constructor (`:1811`): add
  `document.addEventListener("termthemechange", this._onThemeChange);` after the `themechange` add.
- `ext_vt.js` `XtermTerminal.prototype.destroy` (`:2022`): add, on the line **before** the existing pinned statement,
  `if (this._onThemeChange) document.removeEventListener("termthemechange", this._onThemeChange);`
  This keeps the pinned literal `test_term_vt_client.py:2053` intact.
- Grid and every other surface repaint from CSS the moment the attribute changes, so they need no JS.

### 4.4 The per-terminal theme flipper (`.vtthemebtn`)
The contract says the terminal "wont switch unless/until somebody does it from the new config setting". While black,
the flipper would only flip the app chrome behind a terminal that no longer changes, which looks broken. So it is
**hidden while black** (one CSS line in §4.1) and comes back unchanged in "app" mode. `buildToolbar` gets no JS change,
and the existing `TestThemeFlipperInTerminal` source pins still hold.

The CR overlay "Theme" button (`ext_cr_term.js:189`) is the CR app-theme control, and its pane already ignores it.
It is unchanged.

## 5. Live update
- **Same tab:** the Config row calls `applyTermTheme(v)` at once. The CSS repaints grid, toolbar, ctxbar and runner
  output. `termthemechange` makes every live xterm re-read `_xtermTheme(self.container)`. If the server rejects the value,
  `revertTermTheme` snaps it back.
- **Server:** POST `/api/config` runs `apply_overrides`, which repoints `config.TERM_THEME`. The next `GET /` (any tab
  reload, or a newly opened full-tab terminal) bakes in the new value. No restart is needed. A hand-edited config.json
  applies after the next `/api/config` hit, the same as LIVE_WINDOW.

## 6. Tests (each must go red before and green after; prove it by reverting the fix)

New file `tests/test_term_theme.py` (stdlib unittest):

| Class | Asserts | Red before because |
|---|---|---|
| `TestTermThemeConfig` | `"TERM_THEME" in config.EDITABLE`, not in `RESTART_REQUIRED`, in `_PLAIN_ATTR_KEYS`; `VALIDATORS["TERM_THEME"]` accepts `"black"` and `"app"` and rejects `"light"`, `""`, `True`, `None`; `resolve_term_theme({})=="black"`, `({"TERM_THEME":"app"})=="app"`, `({"TERM_THEME":"pink"})=="black"`; `apply_overrides({"TERM_THEME":"app"})` sets `config.TERM_THEME=="app"` (restore in tearDown) | key, validator and resolver do not exist |
| `TestTermThemePage` | default `build_page()` contains `<html data-term-theme="black">`; with `config.TERM_THEME="app"` (restored in tearDown) it contains `<html data-term-theme="app">` and not the black mark | no marker in index.html / page.py |
| `TestTermThemeCssBlock` | in `ext_vt.css`: all 4 selectors `html:not([data-term-theme="app"]) <scope>`; the block's `--x:v` pairs ⊇ every pair parsed from `app.css` line 1 (dict equality on those keys, so a palette edit in app.css that is not mirrored goes red); the dark `--vt-*` and `--rn-*` values; `html:not([data-term-theme="app"]) .vtthemebtn { display: none; }`; `build_page()` contains the selector (guards the gate-miss-on-CSS trap) | block absent |
| `TestTermThemeXtermLive` | XtermTerminal ctor slice (same slicing as `test_term_vt_client.py:2043`) contains `_xtermTheme(self.container)` and `addEventListener("termthemechange", this._onThemeChange)`; the destroy body contains `removeEventListener("termthemechange", this._onThemeChange)`; `mountInto` body contains `_xtermTheme(wrap)` and not `_xtermTheme(container)` | literals absent |
| `TestTermThemeApplyAndConfigRow` | `app.js` defines `function applyTermTheme(`, sets `data-term-theme`, dispatches `CustomEvent("termthemechange"`, and still has exactly 1 `CustomEvent("themechange"`; `ext_cr_dialogs.js` has `serverRow('Terminal colours', 'TERM_THEME'` inside the `active === 'Terminal'` branch, `['black', 'Black'], ['app', 'Follow app theme']`, `window.applyTermTheme(`, and `TERM_THEME: null` in `_ENVCHIP` | absent |

Edits to existing tests (expected consequences of the change, not regressions):
- `tests/test_term_vt_client.py:2046` (`test_xterm_adds_and_removes_the_themechange_listener`): change the literal
  `_xtermTheme();` to `_xtermTheme(self.container);`.
- `tests/test_cr_routes.py:40` `_CFG_ATTRS`: append `"TERM_THEME"` so `_restore` resets it. Add class
  `TestApiConfigTermTheme(_ServerCase)` next to `TestApiConfigIconKeys` (`:317`):
  - POST `{"key":"TERM_THEME","value":"app"}` returns `{"ok":True,"key":"TERM_THEME","value":"app","restart":False}`.
  - GET returns `{"value":"app","overridden":True,"restart":False}` and the value reaches config.json.
  - `"light"` gets 400 `{"error":"invalid value for TERM_THEME"}` and config.json is not created.
  - With no config.json, GET reports `"black"`.
- `tests/test_selfcheck.py` (near `:931`), per conventions rule 9:
  `assert "TERM_THEME" in config.EDITABLE and config.resolve_term_theme({}) == "black" and config.VALIDATORS["TERM_THEME"]("light") == (False, None)`.

Gate: `unset TRACKER_AUTH; make check` must print `selfcheck ok`. If memory pressure kills the full run, run one module
per process.

Manual check after `make serve` (a UI change, so a restart is required). With the app in **light** theme, confirm black on:
1. the Claude login dialog;
2. the pop-up modal (grid and xterm, toggling the renderer switch);
3. a full-tab `?tty=` terminal;
4. the CR inline pane;
5. the command-runner output.

Then flip the app theme, and the terminals must stay black. Set Config → Terminal colours to *Follow app theme*: open
terminals go beige live and the flipper reappears. Back to *Black*: they go black live.

## 7. Sequencing, risk, decisions

**Order.** Each step is independently green.
1. `config.py` + `TestTermThemeConfig` + selfcheck line + `TestApiConfigTermTheme` / `_CFG_ATTRS`. This is the server
   seam, and nothing reads it yet.
2. `index.html` + `page.py` + `TestTermThemePage`. The attribute is emitted but nothing styles it yet.
3. `ext_vt.css` block + flipper hide + `TestTermThemeCssBlock`. This is the visible fix (grid + modal/tab/runner), and
   xterm picks it up through `_build`.
4. `ext_vt.js` (`_onThemeChange` arg, `termthemechange` add/remove, `mountInto.setTheme` arg) + the edit to
   `test_term_vt_client.py:2046` + `TestTermThemeXtermLive`.
5. `app.js` `applyTermTheme` + `ext_cr_dialogs.js` row / `_ENVCHIP` / `TERMINAL_REFERENCE` +
   `TestTermThemeApplyAndConfigRow`.
6. `make check`, restart, manual matrix, `/branch-sync`, re-gate, push the branch to `personal`.

**Files touched:** `aitracker/config.py`, `aitracker/page.py`, `aitracker/web/index.html`, `aitracker/web/ext_vt.css`,
`aitracker/web/ext_vt.js`, `aitracker/web/app.js`, `aitracker/web/ext_cr_dialogs.js`, `tests/test_term_theme.py` (new),
`tests/test_term_vt_client.py`, `tests/test_cr_routes.py`, `tests/test_selfcheck.py`. No change to `server.py`,
`ext_cr_term.js`, `ext_run.js` or `dist/tracker.py`.

**Risky spot: the CSS block.**
1. A stray `*/` or syntax slip silently kills every stylesheet rule after it, and `make check` misses it (known trap).
   Mitigation: `TestTermThemeCssBlock` asserts the block reaches `build_page()`, plus the manual light-theme matrix.
2. The copied palette can drift from `app.css:1`. Mitigation: the pinned dict-equality test.

Fallback if `:not([...])` scoping misbehaves in some engine: use the explicit positive selector
`html[data-term-theme="black"]`. That is safe because `page.py` always emits the attribute. Second fallback for xterm
only: have `_xtermTheme` return the black JS constants when the root attribute is not `"app"`. Guard the root read,
because the node test harnesses' `document` has no `documentElement` (`tests/test_term_vt_exec.py:1525`).

**Decisions you may want to overrule**
- **D1: palette.** The plan uses the app's existing dark terminal palette (`#0c0f15` near-black, `#e6edf3` text).
  - Why: it is what dark-theme users see today, and all ANSI colours are tuned for it.
  - Alternative: pure `#000000` is a one-token change in the block (`--app:#000`, and `--side`/`--chipbg` similar). The
    Control Room pane changes from its warm `#12100E` to this shared black, so all terminals match.
- **D2: per-terminal flipper.** The plan hides `.vtthemebtn` while the setting is Black, so nothing inside a terminal
  can appear to switch its colours.
  - Cost: while a full-screen modal covers the top bar, you can't flip the *app* theme from inside it.
  - Alternative: keep the button visible. It then changes only the app chrome, retitled "Toggle app theme (terminal
    colours: Config → Terminal)".
- (Minor, D3) The command-runner output `.runout` is included as a terminal surface. Dropping it means deleting one selector.
  In "Follow app theme" mode the CR inline pane stays dark, as doc 05 already requires.

## Adversarial review

Reviewer: separate `opus` agent, told to assume the plan is wrong. Verified against the worktree at `418f132` with grep + `sed -n` ranges only (no code, test or browser run). Totals: **0 High, 3 Medium, 7 Low, 1 Info.**

Claims that **held up** when re-derived from the code:
- All three `XtermTerminal`/`Terminal` construction sites pass a `.vttermwrap`: `ext_vt.js:3108` (modal), `:3750` (mountInto), `:4252` (full tab). `switchActiveRenderer` (`:2905`), `mountRenderer` (`:4192`) and mountInto `setRenderer` → `attachRenderer` (`:3764`) rebuild into that same wrap. No other terminal mount exists in `web/`. `termSplit` (`app.js:107`) is a split-button menu, the Manage-terminals panel (`:3313`) is a list, and `peekUrl` (`:3555`) and "New tab" both open the same `?tty=` full tab.
- `ext_vt.css` and `ext_run.css` contain no hex literal and no `html.light` rule except the `--vt-*`/`--rn-*` token pairs (`ext_vt.css:419-430`, `ext_run.css:25-36`). No `ext_cr*.css` rule targets `.vt*` colours (only `ext_cr_dialogs.css:662`, which sets height). So a token block declared *on* the wrap really does beat `html.light`, CR's `.tracker-next` token layer and the inline `setTheme()` write on the CR container (`ext_vt.js:3804-3806`).
- The CR pane wrap is `position:absolute; inset:0` (`ext_cr_term.css:321-324`), so the CR frame never shows around it.
- The config seam is real and matches the plan: `EDITABLE` `:225`, `RESTART_REQUIRED` `:238`, `_v_enum` `:255`, `VALIDATORS` `:300`, `_RESOLVERS` `:581`, `_PLAIN_ATTR_KEYS` `:605`, `apply_overrides` `:628`, `snapshot` `:654`. POST `/api/config` is generic (`server.py:780-801`). `GET /` rebuilds the page on every request (`server.py:446-447`), and `page.py` already does two mark substitutions, `LIVE_MARK` and `TERM_TAB_MARK` (`page.py:20-23`). `dist/tracker.py` bundles no `ext_*` file and no terminal tier (`scripts/bundle.py:52-60`), so it is not affected.
- `segmented()` fires `onChange` on every click, including on the already-active option (`ext_cr_dialogs.js:938-941`). `serverRow`'s `onFail` runs before the re-render (`:1813-1840`). Both match the Icon style idiom.

### Findings

**1. [Medium] The classic pop-up's title bar stays app-themed, so in light mode a beige header sits on top of a black terminal.**
- Defect: the scope is `.vtmb` (the modal body, `ext_vt.js:2093`). The header `.mh` (`ext_vt.js:2062-2090`: title, fork chip, status, New tab, close) is a sibling of the body, so it keeps the root tokens. On top of that, `.modal{background:var(--card);border:1px solid var(--line)}` (`app.css:516`) is declared on the `.modal.vtmodal` element itself.
- Repro: app in light theme, open a terminal. Actual: a beige `#fbf8f0` title bar with dark text above a black pane. Expected: the whole terminal window is black ("all the terminal window ... black").
- Fix direction: scope the whole pop-up window, not only its body. Do NOT touch the shared `.overlay` backdrop or `app.css .modal` itself.
- Way: in the selector list, replace `html:not([data-term-theme="app"]) .vtmb` with `html:not([data-term-theme="app"]) .vtmodal`. `.vtmodal` is set only at `ext_vt.js:2059`, and the selector covers both `.mh` and `.vtmb`. The `.modal` background then reads the `--card` declared on that same element, which is dark.
- Test: the CSS pin asserts the `.vtmodal` selector, red before. Manual check in light theme: the title bar is dark.
- Not covered by this fix: the CR overlay shell (`.cr-term-head` and `.cr-term-controlbar`, `ext_cr_term.css:34-160`) is CR chrome built from CR tokens, and it has its own Theme button. Recommendation: leave it as is (doc 05 already keeps only the pane dark) and list it as decision D4 for the user.

**2. [Medium] D3 is applied to only half of the command-output surfaces: classic `.runout` is in, but the Control Room's own "Run a command" pane is not.**
- Defect: `renderRunOutput` (`ext_cr_dialogs.js:2377-2406`, `pre.cr-outputtext.cr-popout-body`) is the CR equivalent of `ext_run.js`'s `.runout`, and the `command-output` pop-out (`:2311`) is similar. Both are styled with CR tokens (`--surface-*`, `ext_cr_dialogs.css:519`). The app-token block never redeclares those tokens, so adding the selector would not help either.
- Repro: Control Room → run a command, with the app in light theme. Actual: light output pane. The classic runner, under the plan, is black. Result: two different behaviours for one feature.
- Fix direction: keep the scope to real PTY terminal windows, which is what the contract says ("terminal window"). Recommendation: drop `.runout` and the `--rn-*` copy. Do NOT touch `ext_run.css` or any CR output pane. If the user overrules and wants output boxes black, both `.runout` and `.cr-outputtext` have to be added, with a CR-token block for the second.
- Way: delete the `.runout` selector and the `--rn-*` line from the §4.1 block, and change D3 to "excluded; say so in the PR".
- Test: the CSS pin asserts that no `data-term-theme` selector contains `.runout` (a guard, not a red test). The real proof is the manual matrix, with step 5 removed.

**3. [Medium] Copying ~45 palette tokens plus a dict-equality drift test is wider than the defect. The same result is a selector-list addition to the existing dark declarations.**
- Defect: §4.1 copies every declaration of `app.css:1` and `ext_vt.css:419-424` into a second block, then adds a parser test to keep the copy in sync. There are no test pins on `app.css:1` or on the `--vt-*` values (grep: none), so the original rules can be extended directly.
- Repro: n/a. This is design weight: two copies of the palette, one of them guarded by a parser.
- Fix direction: declare the dark tokens once, by adding the terminal scopes to the existing dark rules' selector lists. Do NOT change any token value or the `html.light` rules, and do NOT use `:is()`. An unsupported selector would invalidate the whole rule, and that rule is the app's entire dark palette.
- Way:
  - `app.css:1`: `:root{` becomes `:root,html:not([data-term-theme="app"]) .vttermwrap,html:not([data-term-theme="app"]) .vtmodal,html:not([data-term-theme="app"]) #ext_vt.vtfull{`.
  - `ext_vt.css:419` gets the same change for its `:root {` `--vt-*` rule.
  - `ext_vt.css` keeps only the two new rules: `{color-scheme:dark}` on those three selectors, and `.vtthemebtn{display:none}`.
  - Why it works: on the html element, `html.light` (0,1,1) still beats `:root` (0,1,0), so nothing changes there. On a wrap, only the new selector matches, so the dark values are declared on the wrap itself.
  - Fallback if the user prefers not to touch `app.css`: the plan's copy plus drift test.
- Test: pin the exact new prefix of `app.css` line 1 and of the `--vt-*` rule, and check that `build_page()` contains both. That covers the "a stray `*/` silently kills CSS" trap. Red before.

**4. [Low] The proposed `assertNotIn("_xtermTheme(container)", mountInto body)` stays red even after the code fix.**
- Defect: the mountInto `setTheme` comment at `ext_vt.js:3799` contains the literal `` `_xtermTheme(container)` ``. The plan rewrites only the code line at `:3808`. The `_xtermTheme` doc comment at `:1728-1733` also says every caller reads the root and that mountInto reads "the CALLER's own container", which becomes false.
- Repro: apply §4.2 exactly as written and run `TestTermThemeXtermLive`. Actual: fails. Expected: passes.
- Fix direction: assert positively on the code statement, and rewrite both stale comments. Do NOT change `_xtermTheme`'s body.
- Way:
  - Assert `curTerm.term.options.theme = _xtermTheme(wrap);` is in the mountInto body. Drop the negative assert.
  - In the same edit, rewrite the comments at `:3797-3800` and `:1728-1733` in one sentence each ("reads the wrap, which inherits a caller's inline override in app mode and carries the black tokens otherwise").
- Test: that positive assert, red before.

**5. [Low] The rationale for the new event is overstated (§4.3). The decision is still right.**
- Defect: the plan says a terminal-only `themechange` "would corrupt" the CR theme preference. It would not: the listener returns early when `detail.theme` is not `light`/`dark` (`ext_cr_boot.js:191-192`). The real reasons are the 1-dispatch pin (`test_term_vt_client.py:2009`) and the fact that every `themechange` re-runs Mermaid (`app.js:1063`).
- Repro: n/a.
- Fix direction: keep `termthemechange`, which follows the existing `iconstylechange` precedent (`app.js:169`). Correct the sentence. No code change.
- Way: edit the §4.3 text.
- Test: none.

**6. [Low] The test plan is wider than the change and partly duplicated. Six new classes plus a selfcheck line cover about 40 lines of code.**
- Defect:
  - `TestTermThemeConfig` (validator, resolver, `apply_overrides`) repeats both the selfcheck line and `TestApiConfigTermTheme`.
  - "still exactly 1 `CustomEvent(\"themechange\"`" repeats `test_term_vt_client.py:2009` and is green before the change, so it proves nothing.
  - `TestTermThemePage`'s "app" half is better proven end to end. `_ServerCase._get` (`test_cr_routes.py:186`) already returns the raw `GET /` body.
- Repro: n/a.
- Fix direction: two new classes. The server one proves the real seam (POST → config.json → `apply_overrides` → `GET /`). The client one holds the source pins. Do NOT drop the selfcheck line (conventions rule 9).
- Way: see §Tests in the clean plan.
- Test: each remaining assertion is red when its fix is reverted.

**7. [Low] The Config row's sub-text overclaims what "Follow app theme" does.**
- Defect: the sub-text says "Follow app theme uses the app's light/dark colours" for every terminal. In app mode, the CR inline pane stays dark (`DARK_PANE_THEME`, `ext_cr_term.js:374`, doc 05), and the plan keeps that.
- Repro: set Follow app theme, light app theme, open the CR pane. Actual: dark. The text promises light.
- Fix direction: correct the text only.
- Way: `'Black: every terminal (pop-up, full tab, Control Room pane, login window) stays black in light and dark theme. Follow app theme: terminals use the app\'s light/dark colours; the Control Room pane stays dark.'`
- Test: the existing row pin on `serverRow('Terminal colours', 'TERM_THEME'` is enough. Don't pin prose.

**8. [Low] README goes stale and is missing from the plan's list of files touched.**
- Defect: `README.md:110` says the toolbar "carries a theme toggle button ... flips the same app-wide theme, and an already-open xterm pane re-themes live". That is false under Black. `README.md:214` lists the editable running parameters and the Interface/Terminal knobs without `TERM_THEME`.
- Repro: read the README after the change.
- Fix direction: update both sentences. Nothing else in the README changes.
- Way:
  - `:110`: "Terminals are black by default whatever the app theme (Config → Terminal → Terminal colours; *Follow app theme* restores the toolbar theme toggle and live re-theme)."
  - `:214`: add "terminal colours (`TERM_THEME`: `black` | `app`, default `black`)".
- Test: none (docs).

**9. [Low] Other open tabs stay stale until reload.**
- Defect: the attribute is baked per page load. A second tab keeps the old colours, while its Config row (fetched fresh) shows the new value.
- Repro: tab A sets *Follow app theme*. Tab B, already open, stays black.
- Fix direction: accept it, because it is the same as the documented LIVE_WINDOW behaviour, and tab B is not switching on its own (no contract break). Re-clicking the active segment in B re-applies it (`ext_cr_dialogs.js:938-941`). Document it in the PR. No code change. Optional one-liner, if wanted: in the `active === 'Terminal'` branch, call `window.applyTermTheme(srv.cfg.TERM_THEME.value)` when `srv.cfg` is loaded.
- Way: PR note.
- Test: none.

**10. [Low] D1 side effect: the Control Room window gets two different darks.**
- Defect: under Black, the CR pane area becomes `#0c0f15`, which is cool. The CR frame and status bar stay `#12100E` / `#26221C` (`ext_cr_term.css:278-290, 330+`), which are warm. Today the pane matches the frame.
- Repro: open the CR pane. The terminal is a cool black next to a warm-grey status bar.
- Fix direction: cosmetic, and part of D1. No change unless the user picks a different palette. Mention it in D1.
- Way: D1 text.
- Test: none.

**11. [Info] The "External" terminal (OS terminal app via `TERM_APP`) is outside the app and can't be themed.**
- Fix direction: no change. Say so in the PR so "entire app" isn't read as covering it.

### Verdict on the plan's own tests

| Proposed test | Red before? | Verdict |
|---|---|---|
| `TestTermThemeConfig` | yes | duplicate of the selfcheck line and the API class. Fold in (F6). |
| `TestTermThemePage` | yes | keep the default-black half in the client class. Prove the "app" half via `GET /` in the API class (F6). |
| `TestTermThemeCssBlock` | yes | rewrite for the selector-list design (F3); drop the `.runout` and `--rn-*` parts (F2). |
| `TestTermThemeXtermLive` | yes, but **never turns green** as written | fix per F4. |
| `TestTermThemeApplyAndConfigRow` | partly: the themechange count is green before | drop the count (F6). |
| `TestApiConfigTermTheme` | yes | keep, and add the `GET /` mark assertions. |
| Edit to `test_term_vt_client.py:2046` | n/a | a confirmed expected consequence. The literal changes only by its argument. |
| `_CFG_ATTRS` append | n/a | required, otherwise POSTed values leak across tests. |

## Clean plan (post-review)

Contract and C1–C5 are unchanged. Terminal surfaces covered: the pop-up **window** (`.vtmodal`), every `.vttermwrap` (pop-up, full tab, CR pane, login dialog) and the full tab (`#ext_vt.vtfull`). Command-output boxes are excluded (F2).

**Server (unchanged from §3.2 and §3.3).**
- `config.py`: `TERM_THEME` in `EDITABLE`, `VALIDATORS` (`_v_enum(("black","app"))`), `resolve_term_theme`, `_RESOLVERS`, `_PLAIN_ATTR_KEYS`, plus the seed `TERM_THEME = resolve_term_theme({})`. Not in `RESTART_REQUIRED`.
- `index.html:1`: `<html data-term-theme="black">`.
- `page.py`: `TERM_THEME_MARK` replaced in `read("index.html")` before the `__CSS__`/`__JS__` insertion.
- No `server.py` change.

**CSS (F1, F2, F3).**
- `app.css:1`: change `:root{` to `:root,html:not([data-term-theme="app"]) .vttermwrap,html:not([data-term-theme="app"]) .vtmodal,html:not([data-term-theme="app"]) #ext_vt.vtfull{`. No token value changes, and no `:is()`.
- `ext_vt.css:419`: the same three selectors are added to the `:root {` `--vt-*` rule.
- `ext_vt.css`: append two rules, with a one-line comment pointing at `config.TERM_THEME`:
  - `html:not([data-term-theme="app"]) .vttermwrap, … .vtmodal, … #ext_vt.vtfull { color-scheme: dark; }`
  - `html:not([data-term-theme="app"]) .vtthemebtn { display: none; }`
- `ext_run.css` gets no change.
- Fallback if `app.css` must not be touched: the plan's copied block on the same three selectors, plus its drift test.

**xterm (§4.2, with F4).**
- `_onThemeChange` uses `_xtermTheme(self.container)`.
- mountInto `setTheme` uses `_xtermTheme(wrap)`.
- Rewrite the stale comments at `ext_vt.js:1728-1733`, `:1801-1809` and `:3797-3800`, one sentence each.
- `document.addEventListener("termthemechange", this._onThemeChange)` in the constructor. The matching `removeEventListener` in `destroy` goes on the line **before** the existing pinned statement at `:2022`.

**Live switch (§4.3).**
- `app.js`, after `:171`: add `applyTermTheme(v)`, which sets `data-term-theme` and dispatches `termthemechange`. It follows the `iconstylechange` precedent. Correct the rationale text (F5).

**Config row (§3.4, with F7).**
- First row of the Terminal section: `serverRow('Terminal colours', 'TERM_THEME', <F7 text>, segmented([['black','Black'],['app','Follow app theme']]) + live preview, revertTermTheme)`.
- `_ENVCHIP`: `TERM_THEME: null`.
- `TERMINAL_REFERENCE` (`ext_cr_dialogs.js:653`) text updated.

**Docs (F8).** `README.md:110` and `:214`.

**Tests. Prove each one red by reverting its fix.**
1. `tests/test_cr_routes.py`: append `"TERM_THEME"` to `_CFG_ATTRS`. New `TestApiConfigTermTheme(_ServerCase)`:
   - POST `app` → `{"ok":True,"key":"TERM_THEME","value":"app","restart":False}`.
   - GET snapshot → `{"value":"app","overridden":True,"restart":False}`, and the value is in config.json.
   - `self._get("/")` body contains `<html data-term-theme="app">`.
   - `"light"` → 400 `{"error":"invalid value for TERM_THEME"}`, and no config.json is created.
   - With a fresh config, GET reports `"black"` and `GET /` contains `<html data-term-theme="black">`.
2. `tests/test_term_theme.py`, one class `TestTermThemeClient`:
   - `app.css` line 1 starts with the exact new selector prefix followed by `{--app:#0c0f15`. The `--vt-*` rule has the same three selectors.
   - The `color-scheme:dark` and `.vtthemebtn{display:none}` rules are present, and no `data-term-theme` selector mentions `.runout`.
   - `build_page()` contains the `app.css` prefix and the flipper rule.
   - The XtermTerminal constructor contains the exact `_onThemeChange` statement with `_xtermTheme(self.container)` and the `termthemechange` add. `destroy` contains the remove. The mountInto body contains `curTerm.term.options.theme = _xtermTheme(wrap);`.
   - `app.js` has `function applyTermTheme(` and `CustomEvent("termthemechange"`.
   - The Terminal branch of `ext_cr_dialogs.js` has `serverRow('Terminal colours', 'TERM_THEME'`, and `_ENVCHIP` has `TERM_THEME: null`.
3. `tests/test_selfcheck.py`, near `:931`: the plan's one-line assert.
4. `tests/test_term_vt_client.py:2046`: the literal `_xtermTheme();` becomes `_xtermTheme(self.container);`. This is an expected consequence.

Gate: `unset TRACKER_AUTH; make check` prints `selfcheck ok`. Run one module per process if the full run gets OOM-killed.

**Manual matrix after `make serve`** (UI change, so restart required). With the app in light theme, check:
1. the login dialog;
2. the pop-up, including its title bar, on grid and on xterm, toggling the renderer;
3. a `?tty=` full tab;
4. the CR pane.

Then flip the app theme from the top bar, from the CR Theme button and through OS auto: everything stays black and no toolbar flipper is shown. Switch to *Follow app theme*: the pop-up, full tab and login terminal turn beige live, the flipper returns, and the CR pane stays dark. Switch back to *Black*: they turn black live.

**Sequencing.** Each step is independently green.
1. config + API test + selfcheck.
2. `index.html` + `page.py` (the `GET /` asserts in the API test).
3. CSS selector lists + the two rules + the CSS pins.
4. `ext_vt.js` xterm changes + comment rewrites + the pin edit.
5. `app.js` + Config row + README.
6. Gate, restart, matrix, `/branch-sync`, re-gate, push the branch to `personal`.

**Files touched:** `aitracker/config.py`, `aitracker/page.py`, `aitracker/web/index.html`, `aitracker/web/app.css` (line 1, selector only), `aitracker/web/ext_vt.css`, `aitracker/web/ext_vt.js`, `aitracker/web/app.js`, `aitracker/web/ext_cr_dialogs.js`, `README.md`, `tests/test_term_theme.py` (new), `tests/test_cr_routes.py`, `tests/test_selfcheck.py`, `tests/test_term_vt_client.py`.

**Risky spot.** The `app.css:1` selector list: one invalid selector drops the whole app dark palette. Mitigations: plain `:not([attr])` selectors only, the exact-prefix pin, the `build_page()` check and the manual matrix. Fallback: the copied block from the original plan.

**Decisions for the user**
- **D1 (palette).** App-dark `#0c0f15`, or pure `#000`. Note F10: the CR pane becomes a cool black inside a warm frame.
- **D2 (flipper).** Hidden while Black, or kept and retitled.
- **D3 (now: exclude command-output boxes).** Overrule only if the classic `.runout` and the CR run-output/command-output panes should both be black.
- **D4 (new).** The CR terminal overlay's head and control bar stay CR-themed, with only the pane black. Overrule if the user wants the whole CR window black, which needs a CR-token block on `.cr-term-shell`.

## Reconciliation (main thread)

Spot-check by the main thread: light theme is `html.light{…}` token overrides (app.css:1/12/80); tokens re-declared on the terminal elements beat inheritance. The only light-overridden tokens `ext_vt.css` uses beyond app.css's first `:root` block are `--vt-*-bg`, which the clean plan scopes at `ext_vt.css:419`. No `html.light` rule targets a terminal element directly. Approach confirmed.

| Finding | Verdict | Note |
|---|---|---|
| F1 pop-up title bar stays beige (scope `.vtmb` → `.vtmodal`) | confirmed | accepted |
| F2 command-output boxes half-covered → exclude `.runout` | confirmed | accepted; contract says "terminal window" |
| F3 copied 45-token palette + drift test → add selectors to existing dark rules | confirmed (overbuilt original) | accepted; copy kept only as fallback |
| F4 negative assert fails on stale comment at `ext_vt.js:3799` | confirmed | accepted |
| Test count 6 classes → 2 + selfcheck + one pin edit | overengineered original | accepted |
| F7 Config row text overclaims for CR pane | confirmed | accepted |
| F8 README `:110`/`:214` stale | confirmed | accepted |
| F5 "new event" rationale overstated | overstated | event kept; rationale text fixed |
| F9 other open tabs need reload | confirmed, by design | same as LIVE_WINDOW; document only |
| F10 cool-black pane inside warm CR frame | confirmed, cosmetic | rides on D1 |
| Info: external OS terminal | false alarm for scope | outside the app |
| Missed by both | none found | runtime cascade / xterm live repaint only provable by the manual matrix |

Implementation follows the **Clean plan (post-review)** above, pending user decisions D1–D4.

## Revision 1 (user decisions D1–D4)

What the user decided:
- **D1.** Keep the app's existing dark terminal palette (`#0c0f15`), applied through the clean plan's selector-list approach (F3). The CR pane converges to it.
- **D2 (design change).** The per-terminal theme button `.vtthemebtn` is hidden in the pop-up, the login dialog and the CR pane. It stays in the **full-tab terminal** (`?tty=`, `#ext_vt.vtfull`). There, a click flips *that tab's* terminal between black and the app-light look. The flip is not saved and a reload resets it. The Config setting still sets the default everywhere.
- **D3.** Command-output boxes are excluded. This is already the case in the clean plan (no `.runout`).
- **D4.** In the Control Room, only the overlay pane goes black. Its head and control bar stay CR-themed, as in the clean plan.

Only the pieces that D2 touches change below. Everything else in **Clean plan (post-review)** stands: server, config row, xterm `_onThemeChange` / `setTheme` arguments, `applyTermTheme`, README, the API test class, the selfcheck line and the pin edit at `test_term_vt_client.py:2046`.

### R1.1 What the button does today
- `buildToolbar` (`ext_vt.js:515`) builds `themeBtn` (`:526-530`).
- `renderThemeBtn` (`:531-539`) picks its icon from `html.light`.
- `activateThemeBtn` (`:540-543`) calls the global `toggleTheme()`. That flips the **app** theme for the tab, saves it to `localStorage.theme` (so every tab picks it up on reload) and fires `themechange`. An open xterm then re-themes, and the grid follows the CSS tokens.
- The full tab marks itself with `html.vt-standalone` (`ext_vt.js:4120`, in `bootStandalone`, before the first `mountRenderer`).

### R1.2 Attribute values (one more, DOM-only)
`<html data-term-theme>` can now hold three values:

| Value | Set by | Meaning |
|---|---|---|
| `black` | server | dark tokens declared on every terminal element |
| `app` | server | terminals follow the app theme |
| `light` | full-tab button only | light tokens on `#ext_vt.vtfull`, this tab only |

Notes:
- `light` is never sent to the server and never validated there. `config.VALIDATORS` stays `("black","app")`, and `applyTermTheme` keeps normalising to `black|app`.
- Because of this third value, the dark rules switch from the clean plan's `html:not([data-term-theme="app"])` to the **positive** `html[data-term-theme="black"]`. Otherwise `light` would still match the dark rule, and the result would depend on equal-specificity source order.
- The positive form is safe because the attribute is always present: the `index.html:1` literal is `black`, and `page.py` always substitutes a value.

### R1.3 CSS (these replace the clean plan's CSS bullets)
- **`app.css:1`** (dark tokens): `:root{` becomes
  `:root,html[data-term-theme="black"] .vttermwrap,html[data-term-theme="black"] .vtmodal,html[data-term-theme="black"] #ext_vt.vtfull{`
- **`app.css:2`** (light tokens, new in this revision): `html.light{` becomes
  `html.light,html[data-term-theme="light"] #ext_vt.vtfull{`
  - Inside the full tab, the wrap no longer matches any dark rule, so it inherits these values from `#ext_vt.vtfull`.
  - This holds even when the tab's app theme is dark (no `html.light`).
  - Every token `ext_vt.css` reads is in `app.css:1-2` or in `--vt-*` (checked with a grep over `var(--…)` in `ext_vt.css`).
- **`ext_vt.css:419`** (`:root {` dark `--vt-*`): add the same three `html[data-term-theme="black"] …` selectors.
- **`ext_vt.css:425`** (`html.light {` light `--vt-*`): add `html[data-term-theme="light"] #ext_vt.vtfull`.
- **`ext_vt.css`**, append:
  ```css
  /* TERM_THEME (config.py, served as <html data-term-theme>): black terminals are dark-scheme; the
     per-terminal theme button exists only in the full tab (html.vt-standalone), see _flipTabTermTheme. */
  html[data-term-theme="black"] .vttermwrap, html[data-term-theme="black"] .vtmodal, html[data-term-theme="black"] #ext_vt.vtfull { color-scheme: dark; }
  html[data-term-theme="black"]:not(.vt-standalone) .vtthemebtn { display: none; }
  ```
  - There is no "restore" rule. The full tab is excluded by `:not(.vt-standalone)` on `html` itself, which is a single simple selector.
  - `light` only ever exists in a full tab, so it never needs a hide rule.

### R1.4 `ext_vt.js` button changes (none in the clean plan; all new)
**New module-level helpers.** Insert them *after* the `// ===== shared zoom toolbar …` comment (`:509-514`) and directly before `function buildToolbar(` (`:515`). That keeps them out of `_NOTICE_BANNER_SRC`, which `test_term_vt_exec.py:202-204` slices up to that comment.
```js
// Terminal colours for THIS page: "black" | "app" (server, config TERM_THEME, baked into <html> by page.py)
// or "light" (full-tab only, set by the toolbar button below -- DOM only, never saved; reload resets it).
function _termThemeAttr() {
  var r = document.documentElement;
  return (r && r.getAttribute && r.getAttribute("data-term-theme")) || "black";
}
function _flipTabTermTheme() {
  var next = _termThemeAttr() === "light" ? "black" : "light";
  document.documentElement.setAttribute("data-term-theme", next);
  document.dispatchEvent(new CustomEvent("termthemechange", { detail: { termTheme: next } }));
}
```

**Changes inside `buildToolbar`.**
- `renderThemeBtn` (`:531-539`): replace `var light = document.documentElement.classList.contains("light");` with
  `var a = _termThemeAttr(), light = a === "app" ? document.documentElement.classList.contains("light") : a === "light";`
  and add one line:
  `themeBtn.title = a === "app" ? "Toggle dark/light theme" : "Toggle this tab's terminal black/light (not saved; default is Config → Terminal colours)";`
- `activateThemeBtn` (`:541`): `toggleTheme();` becomes
  `if (_termThemeAttr() === "app") toggleTheme(); else _flipTabTermTheme();`
  - Follow-app mode keeps exactly today's behaviour: it flips the app theme everywhere and is saved to `localStorage.theme`.
  - Black mode only reaches this in the full tab, because the button is hidden everywhere else.
- After `:554`, add `document.addEventListener("termthemechange", renderThemeBtn);`. Inside `bar.disposeThemeBtn` (`:564-567`), add `document.removeEventListener("termthemechange", renderThemeBtn);`.

**Re-theming xterm needs no extra code.**
- The clean plan already registers `XtermTerminal._onThemeChange` on `termthemechange` and has it read `_xtermTheme(self.container)`.
- In the full tab, `self.container` is `.vttermwrap`. In `light` it inherits the light tokens from `#ext_vt.vtfull`. In `black` it declares the dark tokens itself.
- The grid repaints from the CSS alone.

**Existing pins that still hold.** In `TestThemeFlipperInTerminal` (`test_term_vt_client.py:1981-2067`):
- `toggleTheme();` is still a substring of `buildToolbar`.
- No `classList.toggle("light"` and no `localStorage.theme` appear in `buildToolbar`.
- The `themechange` add and remove statements are unchanged.
- `vtthemebtn` is still built only in `buildToolbar`.

### R1.5 Tests (delta to the clean plan's `tests/test_term_theme.py`)
Replace the CSS bullets of `TestTermThemeClient`, and add one Node class. Each assertion must go red when its fix is reverted.
- **CSS pins** (red before; the lines start with `:root{` and `html.light{` today):
  - `app.css` line 1 starts with `:root,html[data-term-theme="black"] .vttermwrap,html[data-term-theme="black"] .vtmodal,html[data-term-theme="black"] #ext_vt.vtfull{--app:#0c0f15`.
  - `app.css` line 2 starts with `html.light,html[data-term-theme="light"] #ext_vt.vtfull{--app:#f4efe3`.
  - In `ext_vt.css`, the dark `--vt-*` rule's selector contains the three black selectors, and the light `--vt-*` rule's selector contains `html[data-term-theme="light"] #ext_vt.vtfull`.
  - `ext_vt.css` contains `html[data-term-theme="black"]:not(.vt-standalone) .vtthemebtn { display: none; }`.
  - `assertNotIn(':not([data-term-theme', app_css + vt_css)`. This guard stops the clean plan's form from coming back next to the new one.
  - `build_page()` contains both `app.css` prefixes and the hide rule. This covers the trap where a stray `*/` silently kills CSS.
- **JS pins:**
  - `ext_vt.js` has `function _termThemeAttr(` and `function _flipTabTermTheme(`, and both are placed before `function buildToolbar(` (index comparison).
  - The `_flipTabTermTheme` body (sliced to `function buildToolbar(`) contains `setAttribute("data-term-theme", next)` and `CustomEvent("termthemechange"`, and does **not** contain `localStorage` or `fetch(`. This proves the flip is not saved.
  - The `buildToolbar` body contains `if (_termThemeAttr() === "app") toggleTheme(); else _flipTabTermTheme();`, `document.addEventListener("termthemechange", renderThemeBtn);` and `document.removeEventListener("termthemechange", renderThemeBtn);`.
- **New `TestTabTermThemeFlipExec`** (`@unittest.skipUnless(_HAS_NODE)`; reuse `from tests.test_term_vt_exec import _run_node, _HAS_NODE`, the cross-module import precedent at `tests/test_agent_routes.py:13`):
  - Slice the real source from `function _termThemeAttr(` up to `function buildToolbar(`. Run it under a fake `document`: a `documentElement` with a get/setAttribute store, plus a `dispatchEvent` that records events. Define `CustomEvent` as `function (n, o) { this.type = n; this.detail = o.detail; }`.
  - With no attribute, `_termThemeAttr()` returns `"black"`.
  - Starting from `black`, the first flip gives `light` and the second gives `black`, with two `termthemechange` events whose details are `light` and `black`.
  - Starting from `app`, one flip gives `light`. This is a defensive path only, because in app mode the button calls `toggleTheme` instead.
  - Red before: the slice markers are missing, so `index()` raises `ValueError`.
- **Unchanged:** `TestApiConfigTermTheme`, the selfcheck line, the edit at `test_term_vt_client.py:2046`, and the xterm, `applyTermTheme` and Config-row pins.

### R1.6 Manual matrix and docs (delta)
**Manual checks (light app theme):**
- The pop-up, the login dialog and the CR pane are black with **no** theme button.
- The full tab is black **with** the button. A click turns the grid and the xterm light. A second click turns them black again.
- Reload the full tab: it is black again.
- Other tabs and the app theme are unchanged, and `localStorage.theme` is untouched.

**Follow app theme:** the button appears everywhere and flips the app theme exactly as it does today.

**Docs:** in `README.md:110`, change the F8 sentence to: "Terminals are black by default whatever the app theme (Config → Terminal → Terminal colours). A full-tab terminal keeps a toolbar button that flips that tab between black and light until reload; with *Follow app theme*, the button flips the app theme as before."

### R1.7 Risk (delta)
- **Risk:** the third DOM-only value is the new moving part.
- **Fallback:** if the positive `black` selectors misbehave, go back to the clean plan's `:not([data-term-theme="app"])` form. Then pick the full-tab light look with a higher-specificity rule `html[data-term-theme="light"] #ext_vt.vtfull .vttermwrap{…light tokens…}`, at the cost of a copied light palette.

**Files touched:** the same as the clean plan. `app.css` now changes on line 2 as well as line 1, and `README.md:110` gets the revised wording.

## Revision 1 review

Reviewer: separate `opus` agent, told to assume Revision 1 is wrong. Verified with grep + `sed -n` only. No code, test or browser run.

Totals: **1 High, 3 Low, 2 Info.**

### What held up
- **The positive `[data-term-theme="black"]` form is safe wherever a terminal can exist.**
  - `GET /` is the only page that hosts terminals (`server.py:446-447`).
  - It always runs `build_page()`, and the plan substitutes the mark there.
  - The bundle ships no `ext_*` file and no terminal tier (`scripts/bundle.py:52-60`).
  - `popOut` windows (`app.js:2680-2692`) are written without the attribute. They carry only diff or narration bodies (callers at `index.html:235, 241`), never a terminal.
  - Node harnesses run JS only and never evaluate this CSS. The vm harness at `test_term_split_menu.py:471` runs all of `ext_vt.js` with `document` as a Proxy, so `_termThemeAttr()` returns a truthy Proxy and never throws. `CustomEvent` is only touched on click.
- **The full-tab hook exists.** `bootStandalone` adds `html.vt-standalone` at `ext_vt.js:4120`, before `mountRenderer`. `.vt-standalone .overlay{display:none!important}` (`ext_vt.css:485-490`) means no pop-up exists inside a full tab. The hide rule selects on `html` itself, so it needs no "restore" rule.
- **The light full tab inside a dark app works.**
  - The line-2 selector declares the light tokens on `#ext_vt.vtfull`. No dark rule matches the wrap while the attribute is `light`, so the wrap, toolbar, ctxbar and status line all inherit light.
  - `ext_vt.css` reads only `app.css:1-2` tokens, `--vt-*` and `--ico-check` (which is not themed). Its JS writes only `var(--app/--text/--ring2)`. `app.css:12/14` (`--pin-*`) and `:80/81` (`--st-*`) are never read by terminal CSS.
  - Lines 1 and 2 each hold exactly one rule of tokens only (one `{` per line).
- **xterm re-themes live on a flip.** `_flipTabTermTheme` dispatches `termthemechange`. That reaches `_onThemeChange`, which reads `_xtermTheme(self.container)`, and that container is the full tab's `termWrap` (`ext_vt.js:4252`).
- **The new listener is cleaned up.** `renderThemeBtn`'s `termthemechange` listener is removed in `disposeThemeBtn`, and both destroys call that (pinned at `test_term_vt_client.py:2033-2038`). In the main page it is also needed: it updates the icon and title when Config switches between app and black.
- **Existing slices are unaffected.**
  - Helpers go after the `// ===== shared zoom toolbar` comment, so they fall outside `_NOTICE_BANNER_SRC` (`test_term_vt_exec.py:202-204`) and the slices at `test_term_vt_client.py:940` and `:961`, which end at that comment.
  - `:2113` (observePane→buildToolbar) only uses `assertIn`.
  - `_function_body("function buildToolbar(")` starts at buildToolbar, so the `localStorage.theme` and `classList.toggle("light"` negative pins (`:2024-2025`) never see the helpers.
  - `toggleTheme();` is still a substring of buildToolbar.
- **`.vtthemebtn` has no competing `display` rule.** `.vtzoombtn` (`ext_vt.css:233`) sets none.

### Findings

**RV1. [High] The selector-list edits to `app.css:1-2` turn `tests/test_state_color_parity_app.py` red. Neither the clean plan nor Revision 1 saw this (missed by both, including my F3).**
- Defect: `_extract_declarations` (`test_state_color_parity_app.py:45-76`) matches `re.escape(selector) + r"\s*\{"` (`:55`), so it needs `{` straight after `:root` or `html.light`.
  - After the edit, line 1 reads `:root,html[...]…{` and line 2 reads `html.light,html[...]…{`. Neither matches any more.
  - So every line-1 token disappears from `app_dark`, and every line-2 token disappears from `app_light`. Only the `:root`/`html.light` blocks at `app.css:12/14/80/81` and the `--vt-*` pair remain.
- Repro: apply R1.3, then run `python -m unittest tests.test_state_color_parity_app`.
  - Actual: `AssertionError: --side not defined in this theme's table` from `_resolve` (`:143-145`), raised by `_resolve("--side", …)` at `:233`, `:439` and `:495-496` (also `--amber-bg`).
  - Expected: green, because no token value changes.
- Fix direction: this is an expected consequence of the selector shape (values are identical), so update the test's parser. Do NOT go back to a copied palette, do NOT change any token, and do NOT loosen any parity assertion.
- Way: in `_extract_declarations`, change `pattern = re.compile(re.escape(selector) + r"\s*\{")` to `pattern = re.compile(re.escape(selector) + r"\s*(?:,[^{}]*)?\{")`. That accepts the selector as the first item of a selector list. Add one sentence to the docstring saying so.
  - After stripping comments, the only `:root,`, `html.light,`, `.tracker-next,` and `.tracker-next.is-dark,` rules in the built CSS are the ones this change adds. The grep over `web/*.css` found only two comment hits, and comments are stripped before parsing.
  - `.tracker-next` still cannot match `.tracker-next.is-dark{`, because the next character is `.`.
  - Do not touch `tests/test_state_colors.py`. It parses only `.tracker-next` blocks in `ext_cr.css`.
- Test: the parity file itself. It goes red after step 3's CSS edit and green after this helper change. Show that order in the commit log or the PR.

**RV2. [Low] When the attribute is missing, JS and CSS disagree, and C2's "missing attribute still renders black" claim is now false.**
- Defect: with the positive selectors, a page without `data-term-theme` gets no dark tokens and no hide rule, so it behaves like "app". But `_termThemeAttr()` returns `"black"` for a missing attribute. A click on the (visible) button outside a full tab would then run `_flipTabTermTheme` instead of `toggleTheme`, a DOM-only flip in the main page.
- Repro: only reachable if the `index.html:1` literal is lost (for example `<html><head>` comes back). Then open the pop-up and click the theme button. Actual: the attribute becomes `light`, which no CSS rule outside the full tab uses, so nothing visible happens. Expected: the app theme toggles, as in app mode.
- Fix direction: make the JS fallback agree with the CSS. Missing means `"app"`. Keep server-served pages always carrying the attribute, which is already pinned by the `GET /` assertions.
- Way: `return (r && r.getAttribute && r.getAttribute("data-term-theme")) || "app";`. Update C2's text to "always present: the `index.html` literal plus page.py substitution; a missing attribute behaves like app".
- Test: the exec class asserts that with no attribute, `_termThemeAttr()` returns `"app"`. Red against the R1.4 text.

**RV3. [Low] `TERMINAL_REFERENCE` and the Config row text don't mention the full-tab button.**
- Defect: the clean plan's reference text says the "theme toggle shows only with Follow app theme". Under Revision 1 it also shows in the full tab.
- Repro: read Config → Terminal → reference after the change.
- Fix direction: text only.
- Way:
  - `TERMINAL_REFERENCE` `'Renderer switch'` row (`ext_cr_dialogs.js:653`): `'Renderer control — xterm (default) or grid, per terminal. Colours: Config → Terminal → Terminal colours. The toolbar theme button shows in a full-tab terminal (flips that tab until reload) and everywhere with Follow app theme.'`
  - Config row sub-text: append `' A full-tab terminal\'s own button flips that tab only, until reload.'`
- Test: none (prose).

**RV4. [Low] Two proposed assertions are not red-before. Label them; don't count them as proof.**
- Defect: `assertNotIn(':not([data-term-theme', …)` passes before the change. The exec case "starting from `app`, one flip gives `light`" tests a path the button never takes, because app mode calls `toggleTheme`.
- Fix direction: keep the first as a named guard (comment: "guard, green before"). Drop the app-start exec case, or keep it marked "defensive".
- Way: test comments only.
- Test: n/a.

**RV5. [Info] Light full-tab xterm only re-themes bg, fg and cursor.** `_xtermTheme` (`ext_vt.js:1734-1741`) leaves xterm's built-in 16-colour ANSI palette in place, and that palette is tuned for dark backgrounds, so bright-white or yellow output is low-contrast on beige. Today's Follow-app light xterm behaves the same. No change; note it in the PR.

**RV6. [Info] Placing the helpers between the section comment and `buildToolbar` separates that comment from its function.** Moving the comment after the helpers would pull them into `_NOTICE_BANNER_SRC`, so keep R1.4's placement and give the helpers their own two-line comment, which R1.4 already has.

## Implementation plan (final)

Self-contained. It folds together the clean plan, Revision 1 and RV1–RV4, and supersedes every earlier section for implementation.

Ground rules:
- Work only in `.claude/worktrees/term-black-default`.
- Edit the sources, never `dist/`.
- No `git stash`, no `pkill`.
- Prefix gate and commit commands with `unset TRACKER_AUTH;`.
- `git commit` runs the full gate (180–380 s), so give it a timeout of at least 400 s.
- Re-read each region right before editing it.

**Decided behaviour**
- `TERM_THEME` (Config → Terminal → "Terminal colours") is `black` (default) or `app`. Black means every terminal uses the app's existing dark palette (`--app:#0c0f15`), whatever the app theme is. This covers:
  - the classic pop-up window, header included;
  - the full tab;
  - the Control Room overlay pane (its head and control bar stay CR-themed);
  - the Claude login dialog.
- Command-output boxes are excluded.
- Under Black, the toolbar theme button is hidden everywhere except the full tab. There it flips **that tab's** terminal between black and light, DOM only and not saved. Under `app`, behaviour is exactly as today.

**Step 1: server setting** (`aitracker/config.py`)
1. `EDITABLE` (`:225-228`): append `"TERM_THEME"`. Do not add it to `RESTART_REQUIRED`.
2. `VALIDATORS` (`:300`, next to `"HEADER_LINE"` at `:312`): `"TERM_THEME":    _v_enum(("black", "app")),  # terminal colours; read at page build`.
3. After `resolve_header_line` (`:490-495`):
   ```python
   def resolve_term_theme(overrides):
       """Terminal colours: "black" (default; every terminal, whatever the app theme) or "app"
       (follow the app's light/dark). No env var -- config.json > built-in "black"."""
       v = overrides.get("TERM_THEME")
       return v if v in ("black", "app") else "black"
   ```
4. `_RESOLVERS` (`:581`): `"TERM_THEME": resolve_term_theme,`.
5. `_PLAIN_ATTR_KEYS` (`:605-607`): append `"TERM_THEME"`.
6. After `HEADER_LINE = resolve_header_line({})` (`:621`): `TERM_THEME = resolve_term_theme({})`.
7. No `server.py` change.

**Step 2: tests for step 1**
1. `tests/test_cr_routes.py:40-41`: append `"TERM_THEME"` to `_CFG_ATTRS`.
2. New `class TestApiConfigTermTheme(_ServerCase)` after `TestApiConfigIconKeys` (`:317`):
   - POST `{"key":"TERM_THEME","value":"app"}` returns `(200, {"ok":True,"key":"TERM_THEME","value":"app","restart":False})`.
   - `_get_json("/api/config")["TERM_THEME"] == {"value":"app","overridden":True,"restart":False}`.
   - `json.load(open(config.CONFIG_FILE))["TERM_THEME"] == "app"`.
   - `_get("/")[1]` contains `b'<html data-term-theme="app">'`. This goes green only after step 3.
   - POST `"light"` returns `(400, {"error":"invalid value for TERM_THEME"})`, and `os.path.exists(config.CONFIG_FILE)` is False.
   - On a fresh case, GET reports `{"value":"black","overridden":False,"restart":False}`, and `GET /` contains `b'<html data-term-theme="black">'`.
3. `tests/test_selfcheck.py`, after `:931`: `assert "TERM_THEME" in config.EDITABLE and "TERM_THEME" not in config.RESTART_REQUIRED and config.resolve_term_theme({}) == "black" and config.VALIDATORS["TERM_THEME"]("light") == (False, None)`.

**Step 3: page attribute**
1. `aitracker/web/index.html:1`: change `<!doctype html><html><head>` to `<!doctype html><html data-term-theme="black"><head>`.
2. `aitracker/page.py`: add `TERM_THEME_MARK = '<html data-term-theme="black">'` next to `TERM_TAB_MARK` (`:7`). In `build_page()`, change `html = read("index.html")` (`:19`) to `html = read("index.html").replace(TERM_THEME_MARK, '<html data-term-theme="%s">' % config.TERM_THEME)`. This runs before the `__CSS__`/`__JS__` insertion.

**Step 4: CSS** (one declaration of each palette; positive selectors only, no `:is()`)
1. `aitracker/web/app.css` line 1: replace the leading `:root{` with `:root,html[data-term-theme="black"] .vttermwrap,html[data-term-theme="black"] .vtmodal,html[data-term-theme="black"] #ext_vt.vtfull{`. Change nothing else on the line.
2. `app.css` line 2: replace the leading `html.light{` with `html.light,html[data-term-theme="light"] #ext_vt.vtfull{`. Change nothing else.
3. `aitracker/web/ext_vt.css:419`: change `:root {` to `:root, html[data-term-theme="black"] .vttermwrap, html[data-term-theme="black"] .vtmodal, html[data-term-theme="black"] #ext_vt.vtfull {`.
4. `ext_vt.css:425`: change `html.light {` to `html.light, html[data-term-theme="light"] #ext_vt.vtfull {`.
5. Append to the end of `ext_vt.css`:
   ```css
   /* TERM_THEME (config.py, served as <html data-term-theme>): black terminals are dark-scheme; the
      per-terminal theme button exists only in the full tab (html.vt-standalone), see _flipTabTermTheme. */
   html[data-term-theme="black"] .vttermwrap, html[data-term-theme="black"] .vtmodal, html[data-term-theme="black"] #ext_vt.vtfull { color-scheme: dark; }
   html[data-term-theme="black"]:not(.vt-standalone) .vtthemebtn { display: none; }
   ```
6. Do not change `ext_run.css`, `ext_cr_term.css` or `ext_cr_term.js`.
7. **RV1 (required, the same commit as items 1–2):** in `tests/test_state_color_parity_app.py:55`, change `pattern = re.compile(re.escape(selector) + r"\s*\{")` to `pattern = re.compile(re.escape(selector) + r"\s*(?:,[^{}]*)?\{")`. Add to the docstring (`:45-53`): "also matches when `selector` is the first item of a selector list (`:root,html[...] .vttermwrap{`)". Prove it: after items 1–2 and before item 7, the parity file is red (`--side not defined`). After item 7 it is green.

**Step 5: `ext_vt.js` xterm wiring**
1. Constructor (`:1810-1811`): the line becomes `this._onThemeChange = function () { if (self.term) self.term.options.theme = _xtermTheme(self.container); };`. After the `themechange` add, insert `document.addEventListener("termthemechange", this._onThemeChange);`.
2. Rewrite the NOTE comment at `:1801-1809` as one sentence: "Reads the wrap (`self.container`), which carries the terminal-colour tokens (TERM_THEME) or, in app mode, inherits the app's / a mountInto caller's override."
3. `destroy` (`:2022`): on the line **before** the existing statement, insert `if (this._onThemeChange) document.removeEventListener("termthemechange", this._onThemeChange);`. Leave the existing line byte-for-byte.
4. mountInto `setTheme` (`:3808`): `curTerm.term.options.theme = _xtermTheme(container);` becomes `curTerm.term.options.theme = _xtermTheme(wrap);`. Rewrite the comment at `:3797-3800` so it no longer contains the literal `_xtermTheme(container)` ("…so it needs an explicit push: `_xtermTheme(wrap)` reads the wrap, which inherits this override in app mode").
5. Rewrite the `_xtermTheme` comment at `:1728-1733` in one sentence ("every caller passes the terminal's own wrap; with no `el` it reads the document root").
6. `_xtermTheme`'s body is unchanged.

**Step 6: full-tab button** (`ext_vt.js`)
1. Insert after the `// ===== shared zoom toolbar …` comment block (ends `:514`) and directly before `function buildToolbar(` (`:515`):
   ```js
   // Terminal colours for THIS page: "black" | "app" (server, config TERM_THEME, baked into <html> by page.py)
   // or "light" (full-tab only, set by the toolbar button below -- DOM only, never saved; reload resets it).
   function _termThemeAttr() {
     var r = document.documentElement;
     return (r && r.getAttribute && r.getAttribute("data-term-theme")) || "app";
   }
   function _flipTabTermTheme() {
     var next = _termThemeAttr() === "light" ? "black" : "light";
     document.documentElement.setAttribute("data-term-theme", next);
     document.dispatchEvent(new CustomEvent("termthemechange", { detail: { termTheme: next } }));
   }
   ```
   The fallback is `"app"` (RV2).
2. In `renderThemeBtn` (`:536`), replace `var light = document.documentElement.classList.contains("light");` with:
   ```js
   var a = _termThemeAttr(), light = a === "app" ? document.documentElement.classList.contains("light") : a === "light";
   themeBtn.title = a === "app" ? "Toggle dark/light theme" : "Toggle this tab's terminal black/light (not saved; default is Config → Terminal colours)";
   ```
3. In `activateThemeBtn` (`:541`), `toggleTheme();   // app.js global …` becomes `if (_termThemeAttr() === "app") toggleTheme(); else _flipTabTermTheme();   // app mode: app.js global (flips, persists, fires "themechange"); else this tab's terminal only`.
4. After `document.addEventListener("themechange", renderThemeBtn);` (`:554`), add `document.addEventListener("termthemechange", renderThemeBtn);`. Inside `bar.disposeThemeBtn` (`:564-567`), add `document.removeEventListener("termthemechange", renderThemeBtn);`.

**Step 7: live switch and Config row**
1. `aitracker/web/app.js`, after `window.applyIconStyle=applyIconStyle;` (`:171`):
   ```js
   // Terminal colours (config TERM_THEME, served pre-paint as <html data-term-theme>). Only the Config row calls this.
   function applyTermTheme(v){const t=v==="app"?"app":"black";document.documentElement.setAttribute("data-term-theme",t);document.dispatchEvent(new CustomEvent("termthemechange",{detail:{termTheme:t}}));}
   window.applyTermTheme=applyTermTheme;
   ```
   It uses its own event, not `themechange`. That keeps the single dispatch pinned at `test_term_vt_client.py:2009` and avoids a Mermaid re-render.
2. `aitracker/web/ext_cr_dialogs.js` `_ENVCHIP` (`:860-879`): add `TERM_THEME: null,   // no env var -- config.json > built-in default`.
3. In `renderSection()`, as the **first** row inside `} else if (active === 'Terminal') {` (`:1951`), above "Terminal renderer":
   ```js
   function revertTermTheme() {
     if (typeof window.applyTermTheme !== 'function') return;
     window.applyTermTheme((srv.cfg && srv.cfg.TERM_THEME && srv.cfg.TERM_THEME.value) || 'black');
   }
   body.appendChild(serverRow('Terminal colours', 'TERM_THEME',
     'Black: every terminal (pop-up, full tab, Control Room pane, login window) stays black in light and dark theme. Follow app theme: terminals use the app\'s light/dark colours; the Control Room pane stays dark. A full-tab terminal\'s own button flips that tab only, until reload.',
     function (value, onCommit) {
       return segmented([['black', 'Black'], ['app', 'Follow app theme']], value || 'black', function (v) {
         if (typeof window.applyTermTheme === 'function') window.applyTermTheme(v);   // live preview
         onCommit(v);
       });
     }, revertTermTheme));
   ```
4. `TERMINAL_REFERENCE` `'Renderer switch'` row (`:653`): use the RV3 text.

**Step 8: client tests** (`tests/test_term_theme.py`, new, stdlib unittest)
1. `class TestTermThemeClient`. Each assertion is red before its step, except where marked as a guard:
   - `app.css` line 1 starts with `:root,html[data-term-theme="black"] .vttermwrap,html[data-term-theme="black"] .vtmodal,html[data-term-theme="black"] #ext_vt.vtfull{--app:#0c0f15`.
   - `app.css` line 2 starts with `html.light,html[data-term-theme="light"] #ext_vt.vtfull{--app:#f4efe3`.
   - `ext_vt.css` contains `:root, html[data-term-theme="black"] .vttermwrap, html[data-term-theme="black"] .vtmodal, html[data-term-theme="black"] #ext_vt.vtfull {`, `html.light, html[data-term-theme="light"] #ext_vt.vtfull {` and `html[data-term-theme="black"]:not(.vt-standalone) .vtthemebtn { display: none; }`.
   - Guard (green before): `':not([data-term-theme' not in app_css + vt_css`, and no `data-term-theme` selector line contains `.runout`.
   - `build_page()` contains both `app.css` prefixes and the hide rule.
   - The XtermTerminal constructor slice (`src[src.index("function XtermTerminal(container, ttyId"):src.index("XtermTerminal.prototype.attach")]`) contains `_xtermTheme(self.container); };` and `document.addEventListener("termthemechange", this._onThemeChange);`.
   - The destroy slice (`_body_until`-style, from `XtermTerminal.prototype.destroy = function` to `// ===== the modal (reuses app.css`) contains `document.removeEventListener("termthemechange", this._onThemeChange);`.
   - The mountInto slice (`function mountInto(container, target, opts) {` → `function copyBuffer()`) contains `curTerm.term.options.theme = _xtermTheme(wrap);`.
   - `ext_vt.js` has `function _termThemeAttr(` and `function _flipTabTermTheme(`, both at an index below `function buildToolbar(`.
   - The slice `function _flipTabTermTheme(` → `function buildToolbar(` contains `setAttribute("data-term-theme", next)` and `CustomEvent("termthemechange"`, and not `localStorage` or `fetch(`.
   - The buildToolbar slice (`function buildToolbar(` → `var zoomOut = document.createElement`) contains `if (_termThemeAttr() === "app") toggleTheme(); else _flipTabTermTheme();`, `document.addEventListener("termthemechange", renderThemeBtn);` and `document.removeEventListener("termthemechange", renderThemeBtn);`.
   - `app.js` has `function applyTermTheme(` and `CustomEvent("termthemechange"`.
   - In `ext_cr_dialogs.js`, the slice from `active === 'Terminal'` to the next `} else if (active ===` contains `serverRow('Terminal colours', 'TERM_THEME'`, and the file contains `TERM_THEME: null`.
2. `class TestTabTermThemeFlipExec`, `@unittest.skipUnless(_HAS_NODE, "node not installed")`, with `from tests.test_term_vt_exec import _run_node, _HAS_NODE`:
   - Run the real slice `function _termThemeAttr(` → `function buildToolbar(` under a fake `document`: a `documentElement` with a `getAttribute`/`setAttribute` dict, plus a `dispatchEvent` that pushes `{type, detail}`. Define `function CustomEvent(n, o) { this.type = n; this.detail = o.detail; }`.
   - Assert: no attribute gives `"app"`. Starting from `black`, flips give `light`, then `black`, with two `termthemechange` events whose details are `light` then `black`.
   - Print one JSON line.
3. `tests/test_term_vt_client.py:2046`: change only `_xtermTheme();` to `_xtermTheme(self.container);` in the pinned literal. This is an expected consequence. Change nothing else in that class.

**Step 9: docs** (`README.md`)
1. `:110`: replace the sentence "The toolbar also carries a **theme toggle** button … re-themes live." with "Terminals are black by default whatever the app theme (Config → Terminal → Terminal colours). A full-tab terminal keeps a toolbar button that flips that tab between black and light until reload; with *Follow app theme*, the button flips the app theme as before."
2. `:214`: in the running-parameters list, add "terminal colours (`TERM_THEME`: `black` | `app`, default `black`)".

**Step 10: verify, then ship**
1. Red-before proof: for each step, revert its source edit and watch its test go red (step 2 tests against step 1; `GET /` marks against step 3; CSS pins and the parity file against step 4; xterm pins against step 5; button pins and the exec class against step 6; app/Config pins against step 7). Then restore.
2. Gate: `unset TRACKER_AUTH; make check` prints `selfcheck ok`. If it is OOM-killed (`Killed: 9`), run one module per process. One `term_vt` backstop failure is a known flake: re-run that module alone.
3. UI change, so restart: `make serve` from the worktree (foreground server; stop it by its PID, never `pkill`).
4. Manual matrix with the app in **light** theme:
   - The login dialog, the pop-up (header included, grid and xterm, switching renderer) and the CR pane are black with **no** theme button.
   - A `?tty=` full tab is black **with** the button. A click turns grid and xterm light; a second click turns them black; a reload is black again. `localStorage.theme` and other tabs are unchanged.
   - Flip the app theme from the top bar, the CR Theme button and OS auto: terminals stay black.
   - Config → *Follow app theme*: open terminals go beige live, the button shows everywhere and flips the app theme, and the CR pane stays dark.
   - Back to *Black*: black live, and the button is hidden outside full tabs.
   - Pop-up title readable in app-light + Black; full-tab flipped light in app-dark readable.
5. Commit in the worktree, ending with the attribution line. Run `/branch-sync`, re-run the gate, then `git push personal term-black-default`. Never push to `main`.
6. PR/notes:
   - Command-output boxes are excluded (D3).
   - CR head and control bar stay CR-themed (D4).
   - Other open tabs need a reload (same as LIVE_WINDOW).
   - Light full-tab xterm keeps xterm's default ANSI palette (RV5).
   - The external OS terminal is out of scope.

**Files touched:** `aitracker/config.py`, `aitracker/page.py`, `aitracker/web/index.html`, `aitracker/web/app.css` (lines 1–2, selectors only), `aitracker/web/ext_vt.css`, `aitracker/web/ext_vt.js`, `aitracker/web/app.js`, `aitracker/web/ext_cr_dialogs.js`, `README.md`, `tests/test_term_theme.py` (new), `tests/test_cr_routes.py`, `tests/test_selfcheck.py`, `tests/test_term_vt_client.py` (one literal), `tests/test_state_color_parity_app.py` (one regex, RV1).

**Risky spot.**
- The risk: `app.css` lines 1–2 now carry selector lists. One invalid selector drops the entire app palette for that theme.
- Mitigations:
  - plain attribute selectors only;
  - the exact-prefix pins;
  - the `build_page()` check;
  - the parity file, which now parses these rules again;
  - the manual matrix.
- Fallback: keep `app.css` lines 1–2 untouched, and put a copied dark block on the three `[data-term-theme="black"]` selectors and a copied light block on `[data-term-theme="light"] #ext_vt.vtfull` in `ext_vt.css`. Add a dict-equality drift test against `app.css` lines 1–2, and then revert the RV1 regex change.

## Reconciliation 2 (main thread)

User decisions: D1 existing dark terminal palette; D2 flipper hidden except in the full-tab terminal, where it flips that tab only (not persisted); D3 exclude output boxes; D4 CR pane only.
RV1 (High) confirmed by the main thread: `tests/test_state_color_parity_app.py:55` builds `re.escape(selector) + r"\s*\{"`, so a selector list on `:root` drops the line-1 tokens. Accepted as an expected-consequence test edit. RV2, RV3, RV4: confirmed, accepted. Info items: no change.
Implement from `## Implementation plan (final)`.

## Implementation review A (server/config/tests)

Reviewer: opus, adversarial. Scope: `aitracker/config.py`, `aitracker/page.py`, `aitracker/web/index.html`, `aitracker/web/ext_cr_dialogs.js` (Config row, `_ENVCHIP`, reference text), `README.md`, and the five test files. Method: a per-file diff, the test modules run, and mutation runs on a `/tmp` rsync copy (the worktree was never edited).

**Verdict: the server half HOLDS. The client live path is UNPROVEN by tests.** The code reads as correct, but nothing in `tests/` would go red if it broke.

### What was checked (evidence)
- **`TERM_THEME` is wired exactly like `HEADER_LINE`.** It is in `EDITABLE` (`config.py:228`), `VALIDATORS` `_v_enum(("black","app"))` (`:312`), `resolve_term_theme` (`:499-503`), `_RESOLVERS` (`:604`), `_PLAIN_ATTR_KEYS` (`:617`) and the seeded attr (`:632`). It is not in `RESTART_REQUIRED`. `server.py:798` `apply_overrides` repoints it, and `GET /` calls `build_page()` on every request (`server.py:447`), so a Config save reaches the next page load.
- **The `page.py:20` substitution runs on `index.html` only,** before the CSS and JS are inlined, so it cannot touch other marks or the `LIVE`/`TERM_TAB` substitutions. The value is resolver-clamped to `black` or `app`, so nothing can be injected.
- **Mutation runs on the copy:**
  - These all went RED:
    - drop the `.replace` in `page.py`;
    - drop `TERM_THEME` from `_PLAIN_ATTR_KEYS`;
    - the validator accepts `"light"`;
    - the resolver defaults to `"app"`;
    - single-quote the `index.html` mark (3 failures);
    - give `_ENVCHIP` an env var.
  - The selfcheck line (`test_selfcheck.py:932`) is executed via `tests.test_tracker.TestSelfcheckSmoke`. It goes RED when the validator accepts `"light"`.
- **`test_state_color_parity_app.py:56` regex.** I compared the old and new matches on the built page. The only new matches are the four intended selector lists: `app.css` lines 1-2 and `ext_vt.css:419` / `:425`. The `.tracker-next` and `.tracker-next.is-dark` match counts are unchanged (2 and 1). The test is not weakened.
- **`test_term_vt_client.py:970`.** `"\n#ext_vt.vtfull {"` still finds the same block as HEAD (`ext_vt.css:501`). The new occurrences at `:419` and `:425` are preceded by a space, not a newline. The test is not weakened.
- **`test_term_vt_client.py:2685`.** The truncation removes only the two appended TERM_THEME lines (`:571-574`). Coverage of the manager breakpoints (`:538-570`) is unchanged today (see R-A2).
- **Text accuracy.**
  - The Config row says "the Control Room pane stays dark". That matches `ext_cr_term.js:204` and `:361`, which force the pane dark via `setTheme`.
  - The reference row and `README` lines 110 and 214 match the hide rule (`ext_vt.css:574`).
  - `#ext_vt.vtfull` exists only in standalone (`ext_vt.js:4143`).
- **Runs.** `tests.test_term_theme`, `tests.test_state_color_parity_app`, `tests.test_cr_routes.TestApiConfigTermTheme`, `tests.test_term_vt_client` (281 tests), `tests.test_cr_dialogs_config_exec` and `tests.test_tracker.TestSelfcheckSmoke` are all green. The node exec case ran (node is present).

### Findings

**R-A1 (Medium): the Config row's live preview and revert, and `applyTermTheme` itself, are untested.**
- **Defect.** `ext_cr_dialogs.js:1953-1964` and `app.js:173` are covered only by text pins (`test_term_theme.py` `test_config_row_and_envchip` and `test_app_js_apply_term_theme`). Four mutants each left `tests.test_term_theme` green, and grep shows no other test references `applyTermTheme`, `revertTermTheme` or the row:
  1. Delete the `window.applyTermTheme(v);   // live preview` call.
  2. Drop `revertTermTheme` as `serverRow`'s `onFail`.
  3. Delete `document.documentElement.setAttribute("data-term-theme",t);` from `applyTermTheme`.
  4. Invert the mapping (`v==="app"?"black":"app"`).
- **Repro.** Mutant 2: the user is on Black and clicks "Follow app theme", and the POST is rejected (read-only viewer → 403). Actual: the terminals stay in app colours until reload, while the control snaps back to Black. Expected: the terminals revert to black. The suite stays green.
- **Fix direction.** Add executed tests only. Do NOT change the row, `serverRow` or `applyTermTheme`; they read as correct.
- **Way.**
  - (a) In `tests/test_cr_dialogs_config_exec.py`, add a second harness. Reuse its fake DOM prelude (everything above `// server state the stubbed fetch`).
    - Before evaluating `ext_cr_dialogs.js`, set `global.applyTermTheme = v => rec.push(v)`.
    - Stub GET `/api/config` → `{TERM_THEME:{value:'black',overridden:false,restart:false}}`, and stub POST to succeed first, then return `ok:false` with `{error:'invalid value for TERM_THEME'}`.
    - Open `config` at section `Terminal` and find the row whose `.cr-cfg-row-name` starts with `Terminal colours`.
    - Click the `.cr-seg-btn` "Follow app theme". Expect `rec == ['app']`, a POST body of `{key:'TERM_THEME',value:'app'}`, and the badge `Saved`.
    - Set the failure flag, then click "Black". Expect `rec == ['app','black','app']` (preview, then the revert to `srv.cfg`'s last-good `app`), and the active segment back on "Follow app theme".
  - (b) In `tests/test_term_theme.py`, add a `TestApplyTermThemeExec` (node, `skipUnless(_HAS_NODE)`).
    - Slice `app.js` from `function applyTermTheme(` to `window.applyTermTheme=`.
    - Run it under the same fake `document` and `CustomEvent` as `TestTabTermThemeFlipExec`.
    - Assert `applyTermTheme('app')` → attr `app` plus one `termthemechange` event with `detail.termTheme=='app'`, and `applyTermTheme('bogus')` → attr `black`.
- **Test that proves it.** Each of the four mutants above turns (a) or (b) RED.
  - (a) catches mutants 1 and 2. Without the preview, `rec` is empty. Without `onFail`, `rec` is `['app','black']`.
  - (b) catches mutants 3 and 4.
- **Note.** The comparable ICON_STYLE row has the same gap today (no exec test of `revertIconPreview`). So this is consistent with precedent, but the brief asked for the live path to be shown working.

**R-A2 (Low): the manager-panel "nothing hidden by viewport" guard is now blind past `/* TERM_THEME`.**
- **Defect.** `test_term_vt_client.py:2685` reads `tail = tail[:tail.index("/* TERM_THEME")]`. Any future manager-panel rule appended after the TERM_THEME block (the end of `ext_vt.css`) escapes `assertNotIn("display: none", tail)` and the breakpoint pins.
- **Repro.** Append `@media(max-width:600px) { .vtmgrfoot { display: none; } }` at the end of `ext_vt.css`. Actual: green. Expected: red. (At HEAD this was red.)
- **Fix direction.** Exclude only the one known rule, not everything after a comment. No CSS change.
- **Way.** Replace that line with `tail = tail.replace('html[data-term-theme="black"]:not(.vt-standalone) .vtthemebtn { display: none; }', "")`. Keep the hide-rule pin in `test_term_theme.test_ext_vt_css_pins`, so a removed rule still goes red there.
- **Test.** The repro append above goes RED with the fix and stays green without it.

**R-A3 (Info, no change): a hand-edited `config.json` `TERM_THEME` reaches `GET /` only after a restart or an `/api/config` hit.**
- `GET /` does not call `apply_overrides`.
- This is the same as `LIVE_WINDOW`, which is baked by the same `build_page`. It is a known pattern. Document it in the PR beside "other open tabs need a reload".

**R-A4 (Info, no change): the standalone bundle always serves `data-term-theme="black"`.**
- `scripts/bundle.py:53-60` / `:88` inline a static page and bypass `build_page`, so `TERM_THEME=app` is ignored in `dist/tracker.py`.
- This is pre-existing: the bundle already ignores `LIVE_MARK` and the `ext_*` files. It is the same as base. Mention it in the PR notes.

**Not examined:** `app.css`, `ext_vt.css` and `ext_vt.js` behaviour (reviewer B's scope). I also could not run a real browser.

## Implementation review B (client) — summary

- **H1 (High, accepted, fixed).** Inherited text `color` resolves at `<html>` with app-theme tokens, so in app-light + `data-term-theme="black"` the pop-up title `.mh .fn` and `.vtpane`/`.vttoolbar` text rendered rgb(43,40,32) on black, and the mirror case flipped the full tab light in an app-dark. Fixed in `ext_vt.css`: the black rule also sets `color: var(--text);` and a new `html[data-term-theme="light"] #ext_vt.vtfull { color: var(--text); }` follows it.
- **I-1 (Info, no change).** The CR pane uses `#0c0f15` in Black; `DARK_PANE_THEME` `#12100E` is inert in that mode. Expected from D1/D4. Note it in the commit.
- **I-2 (Info, no change).** The pop-up's cap and empty states are black too and stay readable.

## Fix round 1

- **FIX 1 (H1).** `aitracker/web/ext_vt.css`: black rule gains `color: var(--text);`, plus the new light `#ext_vt.vtfull` rule. `tests/test_term_theme.py`: new `test_inherited_text_colour_follows_the_surface_palette` and both strings added to `test_built_page_carries_prefixes_and_hide_rule`. Manual matrix line appended in section 7.
  - Red: removing the light rule failed both tests (`light ... not found in` the page / the CSS). Green after restore.
- **FIX 2 (R-A1).** `tests/test_cr_dialogs_config_exec.py`: new `ConfigTermThemeLivePreview` (second harness `_TERM_HARNESS` sharing the fake-DOM prelude): click Follow app theme, then a failed save of Black; asserts applied values `['app','black','app']`, POST bodies, `Saved` badge and the active segment. `tests/test_term_theme.py`: new `TestApplyTermThemeExec` (attr set, `termthemechange` event with `detail.termTheme`, bogus value maps to black).
  - Red: dropping `revertTermTheme` as `onFail` gave `['app','black'] != ['app','black','app']`. Dropping the `setAttribute` in `applyTermTheme` made `TestApplyTermThemeExec` error. Green after restore.
- **FIX 3 (R-A2).** `tests/test_term_vt_client.py`: the cut at `/* TERM_THEME` is replaced by removing only the one hide-rule string.
  - Red: appending `@media(max-width:600px) { .vtmgrfoot { display: none; } }` after the TERM_THEME block failed `test_panel_is_usable_on_phone_and_tablet`. Green after removal.
- **Gate.** `test_term_theme` 15, `test_cr_dialogs_config_exec` 2, `test_term_vt_client` 281, `test_term_vt_exec` 132, `test_page_css` 7, `test_state_color_parity_app` 17 and `test_cr_routes` 38 are all OK, each in its own process. `test_cr_routes` passed alone, so the earlier socket TimeoutError was load. `node --check` is clean on `ext_vt.js`, `app.js` and `ext_cr_dialogs.js`.
