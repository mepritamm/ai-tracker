// Tier 1 — the Resume / Open terminal split button (termSplit in app.js), mounted into #ext_launch.
// Also mounts the (session-less) "+ New terminal" / "+ New Claude session" controls plus their
// directory picker into #ext_launch_side, in the sidebar.
// Registers itself into EXT (app.js's render hook) at load time; never edits app.js itself.
// Concatenated into the same top-level <script> as app.js (see page.py), so `cur`, `EXT`,
// `toast` and `esc` below are the real globals from app.js, not a guess at their shape.
(function () {
  // ponytail: the host/probe gating for the native (external) launch lives in app.js now: see
  // trackerIsLocal() / termExtAllowed() / termExtProbe() / termExtDeny() there for the user-approved
  // exception and the 403 latch. In-browser Resume / Open terminal are NOT covered by it.
  function post(payload) {
    return fetch("/api/term/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  // Resume is Claude-only server-side (term_launch._is_claude, which reads registry.PROVIDERS —
  // that list is the source of truth for these prefixes; this copy only keeps a button from
  // appearing where it would always 400, and the server call is the real gate).
  function isClaudeId(sid) {
    return termResumable(sid);
  }

  function hide(el) {
    el.style.display = "none";
    el.innerHTML = "";
  }

  let lastD;                            // the latest render(d), so a 403 can redraw without the external item
  async function openTerm(mode, extra) {
    if (!cur) return;
    const sidAtClick = cur;
    try {
      const r = await post(Object.assign({ session: cur, mode: mode }, extra || {}));
      const j = await r.json().catch(() => ({}));
      if (r.status === 409 && j.recreate) {   // E1: removed worktree -- one-click recreate (resolved lazily: ext_vt.js loads last)
        const ev = window.ExtVT;
        if (ev && ev.confirmRecreate) {
          ev.confirmRecreate(j, (x) => openTerm(mode, x), () => cur === sidAtClick);
          return;
        }
      }
      if (!r.ok || j.error) {
        if (r.status === 403) {         // feature off, or the server refused us as remote
          // only the external item hides -- the in-browser buttons are a different
          // feature/gate entirely and must not disappear because native launch was refused.
          termExtDeny();
          if (lastD !== undefined) render(lastD);
        }
        alert(j.error || "failed to open terminal");
        return;
      }
      toast(mode === "resume" ? "Resuming in terminal" : "Terminal opened", "this machine only");
    } catch (e) {
      alert("failed to open terminal: " + e);
    }
  }

  // ===== sidebar controls: "+ New terminal" / "+ New Claude session" =====================
  // These used to live in the detail pane, tied to whatever session happened to be selected —
  // but neither one ever touches a session (they open a terminal NOT attached to any existing
  // session's Claude process), so the user asked for them to move to the sidebar and become
  // truly global: no session need be selected, they now ask WHICH DIRECTORY via the picker
  // below. Rendered once at load (unlike render() further down, nothing about this depends on
  // session data, so there is no need to rebuild it on every 2s poll) and never host-gated —
  // see the ponytail comment at the top of this file: that exception is for the native process
  // launcher only, not these in-browser buttons.
  function buildSideControls() {
    var el = document.getElementById("ext_launch_side");
    if (!el) return;
    el.innerHTML =
      '<div class="sidenewgroup">' +
      '<button class="mini extlaunchbtn" id=sidenewcwdbtn ' +
      'title="Start a brand-new terminal in the browser at a directory you choose — not attached to any session">' +
      "+ New terminal</button>" +
      '<button class="mini extlaunchbtn" id=sidenewclaudebtn ' +
      'title="Start a brand-new Claude session in the browser at a directory you choose — it will appear in the sidebar on its own once it starts">' +
      "+ New Claude session</button>" +
      '<button class="mini extlaunchbtn" id=sidemanagetermbtn ' +
      'title="See every terminal running right now — peek into one, close one, or close them all">' +
      ico("menu") + " Manage terminals</button>" +
      "</div>";
    var nc = document.getElementById("sidenewcwdbtn");
    if (nc) nc.onclick = function () { openPicker("cwd"); };
    var ncl = document.getElementById("sidenewclaudebtn");
    if (ncl) ncl.onclick = function () { openPicker("new"); };
    // Terminal domain logic stays in ext_vt.js -- this file only adds the button and calls the
    // module, exactly as the detail pane's "…here" buttons call window.ExtVT.open(cur, ...).
    var mt = document.getElementById("sidemanagetermbtn");
    if (mt) mt.onclick = function () {
      if (window.ExtVT && window.ExtVT.manage) window.ExtVT.manage();
      else alert("in-browser terminal unavailable");
    };
    renderTermBadge();   // the button was just rebuilt -- paint whatever count app.js already has
  }

  // ===== live-terminal count badge on "☰ Manage terminals" ================================
  // Rides app.js's EXISTING sidebar poll (loadSide -> SIDE_EXT) instead of a second timer: no
  // new fetch of the terminal-list route on a tick, and no 403 spam wherever the feature is off.
  // The count itself comes from the server -- app.js only carries the number it read off
  // /api/list's X-Term-Count header (null when the server omitted it), this file never
  // re-derives or hardcodes it (conventions rule 5). `termCount` is app.js's global; see its
  // declaration there. (Terminal-list itself stays owned by ext_vt.js's own manager panel --
  // this file must never call that route directly; see the "reimplementing it" guard test.)
  //
  // null (feature off, or gated off without TRACKER_AUTH) -> no badge at all, not "0" -- the
  // server already decided the count is meaningless here, so showing a chip would imply a
  // working "Manage terminals" panel that will just 403 on click. 0 -> a badge reading "0"
  // (dim/neutral), the honest "feature's on, nothing running" state. >0 -> the same badge,
  // highlighted, exactly like the sidebar's own "N live" chip.
  function renderTermBadge() {
    var mt = document.getElementById("sidemanagetermbtn");
    if (!mt) return;
    var badge = document.getElementById("sidetermbadge");
    if (typeof termCount !== "number" || !isFinite(termCount)) {
      if (badge) badge.remove();
      return;
    }
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "termcountbadge";
      badge.id = "sidetermbadge";
      mt.appendChild(badge);
    }
    badge.textContent = String(termCount);
    badge.classList.toggle("live", termCount > 0);
    badge.title = termCount + " terminal" + (termCount === 1 ? "" : "s") + " running now";
  }
  SIDE_EXT.push(renderTermBadge);

  // ===== the directory picker ==============================================================
  // Reuses app.css's .overlay/.modal/.mh/.mb/.x — the same classes ext_vt.js's own terminal
  // modal builds off (see ext_vt.js's buildOverlay) — instead of inventing a second modal
  // system (conventions rule 4: land a capability once, don't fork it).
  //
  // Built and appended to <body>, never to #ext_launch_side: .side (the sidebar) gets
  // `transform:translateX(...)` at max-width:600px (app.css, the slide-in drawer) — and a
  // transformed ancestor becomes the containing block for any position:fixed descendant, which
  // would silently detach this overlay from the viewport the moment the drawer's transform is
  // set. Building it as a body-level sibling (same as #diffmodal/#msgmodal in index.html, and
  // the same reasoning as ext_vt.js's own overlay, whose #ext_vt mount already lives outside
  // .side) sidesteps that trap entirely.
  var pkOverlay = null, pkTitleEl = null, pkBodyEl = null;

  function buildPicker() {
    pkOverlay = document.createElement("div");
    pkOverlay.className = "overlay";
    pkOverlay.id = "cwdmodal";
    pkOverlay.addEventListener("click", function (ev) { if (ev.target === pkOverlay) closePicker(); });

    var modal = document.createElement("div");
    modal.className = "modal cwdmodal";

    var mh = document.createElement("div");
    mh.className = "mh";
    pkTitleEl = document.createElement("span");
    pkTitleEl.className = "fn";
    var x = document.createElement("span");
    x.className = "x";
    x.innerHTML = ico("close");
    x.title = "Close";
    x.onclick = closePicker;
    mh.appendChild(pkTitleEl);
    mh.appendChild(x);

    pkBodyEl = document.createElement("div");
    pkBodyEl.className = "mb cwdmb";

    modal.appendChild(mh);
    modal.appendChild(pkBodyEl);
    pkOverlay.appendChild(modal);
    document.body.appendChild(pkOverlay);

    // Same convention as ext_vt.js's own modal-Escape listener: only acts while THIS overlay is
    // the one showing, so it never fights app.js's document-level Escape handler (which closes
    // diffmodal/msgmodal/bgdrawer — none of which this touches) or ext_vt.js's own.
    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "Escape") return;
      if (!pkOverlay || pkOverlay.style.display !== "flex") return;
      closePicker();
    });
  }

  function closePicker() {
    if (pkOverlay) pkOverlay.style.display = "none";
  }

  function focusPickerInput() {
    var input = document.getElementById("cwdfreeinput");
    if (input) input.focus();
  }

  function renderPickerBody(mode, state) {
    state = state || {};
    var html = '<div class="cwdlistwrap">';
    if (state.loading) {
      html += '<div class="empty">loading recent directories…</div>';
    } else if (state.note) {
      html += "<div class=\"empty\">" + esc(state.note) + "</div>";
    } else if (!state.cwds || !state.cwds.length) {
      html += '<div class="empty">no recent directories yet</div>';
    } else {
      html += '<div class="cwdlist" id=cwdlist>';
      state.cwds.forEach(function (c) {
        // path/label come straight from the server (GET /api/term/cwds) -- escape both before
        // they reach the DOM, and keep the full path visible (not just on hover) so an
        // ambiguous basename ("api" in three different repos) is still identifiable.
        var p = (c && typeof c.path === "string") ? c.path : "";
        if (!p) return;
        var label = (c && typeof c.label === "string" && c.label) ? c.label : p;
        html += '<button type=button class="cwditem" data-path="' + esc(p) + '" title="' + esc(p) + '">' +
          '<span class="cwdlabel">' + esc(label) + "</span>" +
          '<span class="cwdpath">' + esc(p) + "</span></button>";
      });
      html += "</div>";
    }
    html += "</div>";
    html +=
      '<div class="cwdfreewrap">' +
      '<label class="cwdfreelbl" for=cwdfreeinput>Or type a path</label>' +
      '<div class="cwdfreerow">' +
      '<input id=cwdfreeinput placeholder="/path/to/project or ~/project" autocomplete=off>' +
      '<button type=button class="mini" id=cwdfreebtn>Open</button>' +
      "</div>" +
      '<div class="cwderrmsg" id=cwderrmsg style="display:none"></div>' +
      "</div>";
    pkBodyEl.innerHTML = html;

    var items = pkBodyEl.querySelectorAll(".cwditem");
    for (var i = 0; i < items.length; i++) {
      items[i].onclick = (function (btn) {
        return function () { pickDirectory(btn.getAttribute("data-path"), mode); };
      })(items[i]);
    }
    var input = document.getElementById("cwdfreeinput");
    var goBtn = document.getElementById("cwdfreebtn");
    if (goBtn) goBtn.onclick = function () { pickDirectory(input ? input.value : "", mode); };
    if (input) input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") pickDirectory(input.value, mode);
    });
  }

  function openPicker(mode) {
    // On a phone, these buttons only exist INSIDE the open sidebar drawer (.side, z-index 60) --
    // the picker's own overlay reuses app.css's shared .overlay class (z-index 50), same as
    // every other modal in this app, so left open the drawer would sit ON TOP of the picker and
    // hide it entirely. Every other place that leaves the drawer (e.g. app.js's own pick())
    // already closes it first; this does the same rather than bumping z-index for one modal.
    if (typeof closeDrawer === "function") closeDrawer();
    if (!pkOverlay) buildPicker();
    pkTitleEl.textContent = (mode === "new" ? "New Claude session" : "New terminal") + " — choose a directory";
    renderPickerBody(mode, { loading: true });
    pkOverlay.style.display = "flex";
    // Server-owned (conventions rule 5): the list of recent directories, already de-duplicated,
    // filtered to ones that still exist, and ordered most-recent-first, comes from the server —
    // this file never invents or re-sorts it.
    fetch("/api/term/cwds")
      .then(function (r) {
        if (!r.ok) { var e = new Error("bad status"); e.status = r.status; throw e; }
        return r.json();
      })
      .then(function (j) {
        renderPickerBody(mode, { cwds: (j && j.cwds) || [] });
        focusPickerInput();
      })
      .catch(function (e) {
        // Tier 2 may not have landed GET /api/term/cwds in this worktree yet (or it 404s/errors
        // for some other reason) -- degrade to free-text-only rather than hanging the modal on
        // a spinner that never resolves.
        var note = (e && e.status === 404)
          ? "recent directories aren't available on this server yet — type a path below"
          : "couldn't load recent directories — type a path below";
        renderPickerBody(mode, { cwds: [], note: note });
        focusPickerInput();
      });
  }

  function showPickerBusy() {
    var err = document.getElementById("cwderrmsg");
    if (err) err.style.display = "none";
    var goBtn = document.getElementById("cwdfreebtn");
    if (goBtn) { goBtn.disabled = true; goBtn.textContent = "Opening…"; }
  }

  function showPickerError(msg) {
    var goBtn = document.getElementById("cwdfreebtn");
    if (goBtn) { goBtn.disabled = false; goBtn.textContent = "Open"; }
    var err = document.getElementById("cwderrmsg");
    if (!err) return;
    err.textContent = msg;             // may be server-supplied (a 400's error) -- textContent, never innerHTML
    err.style.display = "";
  }

  // mode is "cwd" (a plain shell), "new" (a fresh `claude`) or "resume". Without opts.session this
  // is the session-less form of the POST /api/term/pty route ext_vt.js's openVT() uses; a
  // `session` in opts switches to the session-scoped form (the server ignores `cwd` then). May
  // 404/400 where unsupported -- handled below, not left to fail silently or hang.
  function pickDirectory(raw, mode, prompt, opts) {
    var path = (raw == null ? "" : String(raw)).trim();
    // A leading "~" is left exactly as typed -- this file never invents a home directory of its
    // own (conventions rule 5: never invent data the server should supply). The server expands
    // it the same way every other path in this codebase is expanded (os.path.expanduser, see
    // config.py's PROJECTS/AUGMENT_DIR/TASKS_DIR); trimming is the only normalisation done here.
    if (!path) {
      showPickerError("choose or type a directory first");
      return Promise.resolve({ ok: false, error: "choose or type a directory first" });
    }
    showPickerBusy();
    var body = { cwd: path, cols: 100, rows: 30, mode: mode };
    if (prompt) body.prompt = prompt;   // optional first prompt for a `new` or `resume` session (ExtLaunch.openAt)
    if (opts && opts.session) body.session = opts.session;       // resume a specific session (pending work)
    if (opts && opts.recreate) body.recreate = opts.recreate;    // token from a confirmed worktree recreate
    if (opts && (opts.gateway === "anthropic" || opts.gateway === "openrouter")) body.gateway = opts.gateway;
    return fetch("/api/term/pty", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        return r.json().catch(function () { return {}; })
          .then(function (j) { return { ok: r.ok, status: r.status, j: j }; });
      })
      .then(function (res) {
        if (res.status === 409 && res.j && res.j.recreate && window.ExtVT && window.ExtVT.confirmRecreate) {
          window.ExtVT.confirmRecreate(res.j, function (x) {
            var p = pickDirectory(raw, mode, prompt, Object.assign({}, opts, x));
            if (opts && typeof opts.onResult === "function") p.then(opts.onResult);   // the retry's real outcome (nested 409s recurse with onResult)
          });
          return { ok: false, error: res.j.error, recreate: true };
        }
        if (res.j && res.j.tty && window.ExtVT && window.ExtVT.bindTty) window.ExtVT.bindTty(res.j.tty, res.j.session || (opts && opts.session) || "");   // "" = session-less shell
        if (!res.ok || !res.j || !res.j.tty) {
          var emsg = (res.j && res.j.error) ||
            (res.status === 404 ? "opening a terminal at a chosen directory isn't available on this server yet" :
              res.status === 403 ? "in-browser terminal is disabled — set TRACKER_TERMINAL=1 and TRACKER_AUTH" :
                "failed to open a terminal there");
          showPickerError(emsg);
          return { ok: false, error: emsg };
        }
        closePicker();
        // opts.tab === false: the caller mounts the terminal itself (ExtVT.mountInto) -- open no tab.
        if (opts && opts.tab === false) return { ok: true, tty: res.j.tty, renderer: res.j.renderer || "grid", notice: res.j.notice || "" };
        if (res.j.attached) toast("Session already open in a terminal", "nothing was typed — use Copy prompt");
        else toast(mode === "new" ? "Starting a new Claude session" : mode === "resume" ? "Resuming session" : "Terminal opened", path);
        // Reuses ext_vt.js's EXISTING standalone-tab path (?tty=...) -- the same URL scheme its
        // own openNewTab() builds -- instead of duplicating the grid/xterm renderer in this
        // file (conventions rule 4: don't fork a capability that already exists). `&sid=` is added
        // only when a session is set; a session-less terminal omits it, and ext_vt.js's
        // bootStandalone() treats a missing ?sid= as "no context bar", not an error.
        // F9: per-tab hostname via ext_vt.js's termTabOrigin -- NOT location.origin -- so this
        // tab gets its own Chrome per-host connection budget. Same helper as ext_vt.js/
        // ext_cr_term.js, no second copy.
        var url = (window.ExtVT && window.ExtVT.termTabOrigin ? window.ExtVT.termTabOrigin(res.j.tty) : location.origin) + location.pathname + "?tty=" + encodeURIComponent(res.j.tty) +
          "&mode=" + encodeURIComponent(mode) +
          "&renderer=" + encodeURIComponent(res.j.renderer || "grid") +
          "&forked=" + (res.j.forked ? "1" : "0") +
          ((res.j.session || (opts && opts.session)) ? "&sid=" + encodeURIComponent(res.j.session || opts.session) : "") +
          (res.j.notice ? "&notice=" + encodeURIComponent(res.j.notice) : "");
        var w = window.open(url, "_blank");
        if (!w) alert("Popup blocked — allow popups for this page to open a new tab.");
        return res.j.attached ? { ok: true, attached: true } : { ok: true };
      })
      .catch(function (e) {
        var cmsg = "failed to reach the server: " + e;
        showPickerError(cmsg);
        return { ok: false, error: cmsg };
      });
  }

  // The single Resume path (pending-work modal, both views): open a terminal at a
  // cwd (session-less, or resuming opts.session), optionally with a first prompt. Resolves {ok, error}; never rejects.
  window.ExtLaunch = { openAt: function (p, m, pr, o) { return pickDirectory(p, m, pr, o); } };

  buildSideControls();

  // Tier 3 rewires the primary action: both buttons now open the in-browser terminal (ext_vt.js,
  // exposed as window.ExtVT) instead of launching a native process. The native Terminal/iTerm
  // launch stays reachable as a small secondary "↗ External …" control -- the user asked for the
  // in-browser terminal to be the default, not for the native launch to disappear.
  //
  // Naming pairs the two remaining detail-pane buttons by WHERE the terminal opens, not by what
  // it does: "…here" = in-browser (this page); "External …" = the Mac's own Terminal/iTerm,
  // this-machine-only. The THIRD pair, "+ New …" (spawns a terminal that is NOT attached to any
  // existing session's Claude process -- a plain shell, or a shell that immediately runs
  // `claude` so a genuinely new session starts) has moved to the sidebar (buildSideControls
  // above) since it never depended on a session in the first place.
  //
  // The two pairs left here live in DIFFERENT gating regimes:
  //  - in-browser "…here" buttons: never host-gated (conventions rule: no control hidden by
  //    host/viewport -- exactly as usable over the tunnel as any other panel). A disabled server
  //    feature (TRACKER_TERMINAL unset) surfaces as an in-modal error on click, not as a missing
  //    button -- see ExtVT.open's 403 handling in ext_vt.js.
  //  - the split's external item: gated by trackerIsLocal() / termExtAllowed() and latched off by
  //    termExtDeny() (all in app.js), justified by the ponytail comment at the top of this file.
  function render(d) {
    const el = document.getElementById("ext_launch");
    if (!el) return;
    lastD = d;
    if (!cur) return hide(el);
    el.style.display = "";
    const resumable = isClaudeId(cur);

    // Server-owned note (registry.parse_any -> meta.term_home_note); rendered verbatim, never derived
    // here. Empty (Auggie, or nothing to say) renders nothing.
    const homeNote = d && d.meta && typeof d.meta.term_home_note === "string" ? d.meta.term_home_note : "";
    // Split button (termSplit, app.js): Resume is the primary for a Claude id with "Open terminal" +
    // the one external item in the caret's list; a non-Claude id has Open terminal as the primary.
    // The pane is rebuilt on every 2 s poll: carry an open menu and focus across it.
    const snap = termSplitSnapshot("ext_launch:");
    el.innerHTML = homeNote ? '<div class="extlaunchnote" data-el="homenote">' + esc(homeNote) + "</div>" : "";
    const split = termSplit({
      key: "ext_launch:" + cur, primaryCls: "mini extlaunchbtn", caretCls: "mini extlaunchbtn", resumable,
      icons: { resume: ico("redo"), open: ico("play") },
      titles: {
        resume: "Resume this session in a terminal right here in the browser (claude --resume)",
        open: "Open a terminal right here in the browser, cd'd to this session's working directory",
      },
    });
    if (el.firstChild) el.insertBefore(split, el.firstChild); else el.appendChild(split);
    const ext = termExtAllowed();
    termSplitSet(split, { resumable, ext: ext === true });
    if (ext === null) termExtProbe().then(() => render(d));
    termSplitOn(split, {
      resume: () => window.ExtVT ? window.ExtVT.open(cur, "resume") : alert("in-browser terminal unavailable"),
      open: () => window.ExtVT ? window.ExtVT.open(cur, "cwd") : alert("in-browser terminal unavailable"),
      external: () => openTerm(resumable ? "resume" : "cwd"),
    });
    termSplitRestore(snap);
  }

  EXT.push(render);
})();
