// Tier 1 — "Open terminal here" / "Resume in terminal" buttons, mounted into #ext_launch.
// Registers itself into EXT (app.js's render hook) at load time; never edits app.js itself.
// Concatenated into the same top-level <script> as app.js (see page.py), so `cur`, `EXT` and
// `toast` below are the real globals from app.js, not a guess at their shape.
(function () {
  // ponytail: deliberate, user-approved exception to the "never gate behaviour by host" rule in
  // .claude/rules/conventions.md. Every other feature in this app works the same over a tunnel
  // as on localhost; this one launches an OS process on whatever machine is running the server,
  // so it must never be OFFERED to a remote viewer. It is cosmetics only — curl ignores it, and
  // the server is what actually refuses (term_launch._local_caller). Do not "fix" it to match
  // the usual rule, and do not mistake it for the security boundary.
  function localOnly() {
    return location.hostname === "localhost" || location.hostname === "127.0.0.1";
  }

  // Server owns policy (conventions rule 5): whether the terminal routes exist at all is
  // TRACKER_TERMINAL + TRACKER_AUTH, which only the server knows. Tier 2 is concurrently adding
  // GET /api/term/status, so we must not invent a route here — instead we ask the route we
  // already have: a POST with an empty session runs term_gate.guard() FIRST, so it comes back
  // 403 when the feature is off and 400 ("session required") when it is on. Nothing is launched
  // either way. One probe per page load; any later 403 (e.g. proxied) latches the buttons off.
  var allowed = null;                   // null = not asked yet, true/false = the server's answer
  var probing = null;

  function post(payload) {
    return fetch("/api/term/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  function probe() {
    if (!probing) {
      probing = post({ session: "" })
        .then(function (r) { allowed = r.status !== 403; })
        .catch(function () { allowed = false; });
    }
    return probing;
  }

  // Resume is Claude-only server-side (term_launch._is_claude, which reads registry.PROVIDERS —
  // that list is the source of truth for these prefixes; this copy only keeps a button from
  // appearing where it would always 400, and the server call is the real gate).
  function isClaudeId(sid) {
    return !!sid && !/^(auggie|augment-vscode|augment-cursor):/.test(sid);
  }

  function hide(el) {
    el.style.display = "none";
    el.innerHTML = "";
  }

  async function openTerm(mode) {
    if (!cur) return;
    try {
      const r = await post({ session: cur, mode: mode });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.error) {
        if (r.status === 403) {         // feature off, or the server refused us as remote
          allowed = false;
          // only the native sub-section hides -- the in-browser buttons are a different
          // feature/gate entirely and must not disappear because native launch was refused.
          const nat = document.getElementById("extnative");
          if (nat) { nat.style.display = "none"; nat.innerHTML = ""; }
        }
        alert(j.error || "failed to open terminal");
        return;
      }
      toast(mode === "resume" ? "Resuming in terminal" : "Terminal opened", "this machine only");
    } catch (e) {
      alert("failed to open terminal: " + e);
    }
  }

  // Tier 3 rewires the primary action: both buttons now open the in-browser terminal (ext_vt.js,
  // exposed as window.ExtVT) instead of launching a native process. The native Terminal/iTerm
  // launch stays reachable as a small secondary "↗ External …" control -- the user asked for the
  // in-browser terminal to be the default, not for the native launch to disappear.
  //
  // Naming pairs the four original buttons by WHERE the terminal opens, not by what it does:
  // "…here" = in-browser (this page); "External …" = the Mac's own Terminal/iTerm, this-machine-
  // only. A third pair, "+ New …", spawns a terminal that is NOT attached to any existing
  // session's Claude process -- a plain shell, or a shell that immediately runs `claude` so a
  // genuinely new session starts (it will show up in this app's own sidebar once it does). Both
  // "+ New …" buttons are in-browser (ext_vt.js) like the top pair, so they share its gating.
  //
  // The three pairs live in DIFFERENT gating regimes:
  //  - in-browser buttons ("…here" and "+ New …"): never host-gated (conventions rule: no
  //    control hidden by host/viewport -- these are exactly as usable over the tunnel as any
  //    other panel). A disabled server feature (TRACKER_TERMINAL unset) surfaces as an in-modal
  //    error on click, not as a missing button -- see ExtVT.open's 403 handling in ext_vt.js.
  //    "+ New Claude session" sends mode:"new", which term_vt.py's /api/term/pty does not
  //    support yet (as of this writing it 400s any mode other than "cwd"/"resume") -- that is
  //    NOT this file's gap to close; ExtVT.open's existing error handling already surfaces
  //    whatever the server says in the terminal modal instead of failing silently or leaving a
  //    dead terminal open, so no extra client-side handling is needed here.
  //  - native "↗ External …" buttons: unchanged from before -- localOnly() + the existing
  //    /api/term/open probe-and-latch, both already justified by the ponytail comment above.
  function render(d) {
    const el = document.getElementById("ext_launch");
    if (!el) return;
    if (!cur) return hide(el);
    el.style.display = "";
    const resumable = isClaudeId(cur);

    const vtHtml =
      '<button class="mini extlaunchbtn" id=extvtopenbtn ' +
      'title="Open a terminal right here in the browser, cd\'d to this session\'s working directory">' +
      "▶ Open terminal here</button>" +
      (resumable
        ? '<button class="mini extlaunchbtn" id=extvtresumebtn ' +
          'title="Resume this session in a terminal right here in the browser (claude --resume)">' +
          "⟲ Resume terminal here</button>"
        : "");

    const newHtml =
      '<span class="extlaunchgroup" id=extnewgroup>' +
      '<span class="extlaunchcap">new</span>' +
      '<button class="mini extlaunchbtn" id=extnewcwdbtn ' +
      'title="Start a brand-new terminal right here in the browser, cd\'d to this session\'s working directory — not attached to any existing session">' +
      "+ New terminal</button>" +
      '<button class="mini extlaunchbtn" id=extnewclaudebtn ' +
      'title="Start a brand-new Claude session right here in the browser, cd\'d to this session\'s working directory — it will appear in the sidebar on its own once it starts">' +
      "+ New Claude session</button>" +
      "</span>";

    let nativeHtml = "";
    if (localOnly()) {
      if (allowed === false) {          // latched off by a previous 403 -- nothing native this cycle
        nativeHtml = "";
      } else if (allowed === null) {    // not answered yet: probe, then redraw once it resolves
        probe().then(function () { render(d); });
      } else {
        nativeHtml =
          '<span id=extnative>' +
          '<button class="mini extlaunchbtn" id=extopenbtn ' +
          'title="Open an external Terminal/iTerm window, cd\'d here — this machine only">↗ External terminal</button>' +
          (resumable
            ? '<button class="mini extlaunchbtn" id=extresumebtn ' +
              'title="Resume via claude --resume in an external Terminal/iTerm window — this machine only">↗ External resume</button>'
            : "") +
          "</span>";
      }
    }

    el.innerHTML = vtHtml + newHtml + nativeHtml;
    const vb = document.getElementById("extvtopenbtn");
    if (vb) vb.onclick = () => window.ExtVT ? window.ExtVT.open(cur, "cwd") : alert("in-browser terminal unavailable");
    const vr = document.getElementById("extvtresumebtn");
    if (vr) vr.onclick = () => window.ExtVT ? window.ExtVT.open(cur, "resume") : alert("in-browser terminal unavailable");
    const nc = document.getElementById("extnewcwdbtn");
    if (nc) nc.onclick = () => window.ExtVT ? window.ExtVT.open(cur, "cwd") : alert("in-browser terminal unavailable");
    const ncl = document.getElementById("extnewclaudebtn");
    if (ncl) ncl.onclick = () => window.ExtVT ? window.ExtVT.open(cur, "new") : alert("in-browser terminal unavailable");
    const ob = document.getElementById("extopenbtn");
    if (ob) ob.onclick = () => openTerm("cwd");
    const rb = document.getElementById("extresumebtn");
    if (rb) rb.onclick = () => openTerm("resume");
  }

  EXT.push(render);
})();
