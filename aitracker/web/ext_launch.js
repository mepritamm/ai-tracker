// Tier 1 — "Open terminal here" / "Resume in terminal" buttons, mounted into #ext_launch.
// Registers itself into EXT (app.js's render hook) at load time; never edits app.js itself.
// Concatenated into the same top-level <script> as app.js (see page.py), so `cur`, `EXT` and
// `toast` below are the real globals from app.js, not a guess at their shape.
(function () {
  // ponytail: deliberate, user-approved exception to the "never gate behaviour by host" rule in
  // .claude/rules/conventions.md. Every other feature in this app works the same over a tunnel
  // as on localhost; this one launches an OS process on whatever machine is running the server,
  // so it must never be offered to a remote viewer even though /api/term/open also refuses any
  // caller whose client_address isn't 127.0.0.1. Do not "fix" this to match the usual rule.
  function localOnly() {
    return location.hostname === "localhost" || location.hostname === "127.0.0.1";
  }

  // Resume is Claude-only server-side (term_launch._is_claude); this mirrors that just to keep
  // the button from appearing where it would always 400 — the server call is the real gate.
  function isClaudeId(sid) {
    return !!sid && !/^(auggie|augment-vscode|augment-cursor):/.test(sid);
  }

  async function openTerm(mode) {
    if (!cur) return;
    try {
      const r = await fetch("/api/term/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session: cur, mode: mode }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.error) {
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
    if (!localOnly()) {
      el.style.display = "none";
      el.innerHTML = "";
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
