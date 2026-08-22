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
          const el = document.getElementById("ext_launch");
          if (el) hide(el);
        }
        alert(j.error || "failed to open terminal");
        return;
      }
      toast(mode === "resume" ? "Resuming in terminal" : "Terminal opened", "this machine only");
    } catch (e) {
      alert("failed to open terminal: " + e);
    }
  }

  function render(d) {
    const el = document.getElementById("ext_launch");
    if (!el) return;
    if (!localOnly() || allowed === false) return hide(el);
    if (allowed === null) {             // not answered yet: stay hidden, then draw if allowed
      hide(el);
      probe().then(function () { if (allowed) render(d); });
      return;
    }
    el.style.display = "";
    const resumable = isClaudeId(cur);
    el.innerHTML =
      '<button class="mini extlaunchbtn" id=extopenbtn ' +
      'title="Open Terminal/iTerm here, cd\'d to this session\'s working directory — this machine only">' +
      "▶ Open terminal here</button>" +
      (resumable
        ? '<button class="mini extlaunchbtn" id=extresumebtn ' +
          'title="Open a terminal and run claude --resume for this session — this machine only">' +
          "⟲ Resume in terminal</button>"
        : "");
    const ob = document.getElementById("extopenbtn");
    if (ob) ob.onclick = () => openTerm("cwd");
    const rb = document.getElementById("extresumebtn");
    if (rb) rb.onclick = () => openTerm("resume");
  }

  EXT.push(render);
})();
