// Tier 2 — embedded command runner. Mounts into #ext_run; pushes one fn(d) onto EXT so it is
// re-run on every 2s render. Everything lives in an IIFE: this file is concatenated into the same
// <script> as app.js, so a bare `const` here would collide with app.js's globals.
//
// Rendering is SGR-ONLY: `ESC [ ... m` becomes a <span class="a31">, and every other CSI/OSC is
// stripped. Cursor addressing is Tier 3's job by definition. Command output is UNTRUSTED, so
// every text run is HTML-escaped before it is inserted.
(function () {
  var host = document.getElementById("ext_run");
  if (!host) return;
  var built = false, enabled = null, job = null, es = null, sid = "", cwd = "";

  function E(s) { return (s || "").replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  // --- SGR -> spans -------------------------------------------------------
  function sgrClass(params) {
    // -> {reset, cls}. "0;31m" both closes what is open and opens red, so the two are separate.
    var reset = false, out = [];
    (params || "0").split(";").forEach(function (p) {
      var n = parseInt(p || "0", 10);
      if (n === 0) { reset = true; out = []; }
      else if (n === 1) out.push("ab");
      else if (n === 3) out.push("ai");
      else if (n === 4) out.push("au");
      else if (n === 7) out.push("ar");
      else if ((n >= 30 && n <= 37) || (n >= 90 && n <= 97) || (n >= 40 && n <= 47)) out.push("a" + n);
      // BOTH background ranges -- not just 40-47 -- for the same reason ext_vt.js's sgrRunClass
      // takes both: term_vt.py's Screen._sgr (the shared server-side SGR parser both Tier 2 and
      // Tier 3 stream through) stores a direct aixterm bright-background code (100-107) VERBATIM
      // rather than normalising it, so a program emitting `\x1b[100m` directly used to produce no
      // class at all here. Named "a100".."a107" (not "ag100" or similar) to match this file's own
      // "a" + n scheme, which already uses one prefix for both fg and bg classes.
      else if (n >= 100 && n <= 107) out.push("a" + n);
    });
    return { reset: reset, cls: out.join(" ") };
  }
  function stripNonSgr(s) {
    return s
      .replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, "")        // OSC ... BEL/ST
      .replace(/\x1b\[[0-9;?]*[^m0-9;?]/g, "")                  // every CSI that is not SGR
      .replace(/\x1b[@-Z\\-_]/g, "")                            // two-char escapes
      .replace(/\r(?!\n)/g, "")                                 // lone CR (progress bars): drop it
      .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, "");            // stray control bytes
  }
  function ansiHtml(raw) {
    var s = stripNonSgr(raw), re = /\x1b\[([0-9;]*)m/g, out = "", last = 0, open = 0, m;
    while ((m = re.exec(s))) {
      out += E(s.slice(last, m.index));
      var g = sgrClass(m[1]);
      if (g.reset) { while (open > 0) { out += "</span>"; open--; } }
      if (g.cls) { out += '<span class="' + g.cls + '">'; open++; }
      last = re.lastIndex;
    }
    out += E(s.slice(last));
    while (open > 0) { out += "</span>"; open--; }
    return out;
  }

  // --- panel --------------------------------------------------------------
  function build() {
    host.innerHTML =
      '<div class="card" id=runcard><h2><span>▶ Run a command</span>' +
      '<span class=cnt id=runstate></span></h2>' +
      '<div class=cbody style="padding:10px 12px">' +
      '<div class=runbar><input id=runcmd class=runinput placeholder="git status" spellcheck=false>' +
      '<button class=mini id=runbtn>Run</button><button class=mini id=runkill disabled>Stop</button></div>' +
      '<div class=runhint id=runhint></div>' +
      '<pre class=runout id=runout></pre></div></div>';
    document.getElementById("runbtn").onclick = start;
    document.getElementById("runkill").onclick = stop;
    document.getElementById("runcmd").addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") { ev.preventDefault(); start(); }
    });
    built = true;
  }
  function setState(t) { var e = document.getElementById("runstate"); if (e) e.textContent = t || ""; }
  function append(text) {
    var pane = document.getElementById("runout");
    if (!pane) return;
    var atEnd = pane.scrollTop + pane.clientHeight >= pane.scrollHeight - 20;
    pane.insertAdjacentHTML("beforeend", ansiHtml(text));
    if (atEnd) pane.scrollTop = pane.scrollHeight;
  }
  function closeStream() { if (es) { es.close(); es = null; } }

  function start() {
    if (es) return;
    var cmd = (document.getElementById("runcmd").value || "").trim();
    if (!cmd) return;
    document.getElementById("runout").innerHTML = "";
    append("\x1b[90m$ " + cmd + "\x1b[0m\n");
    setState("starting…");
    fetch("/api/term/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: sid, cmd: cmd })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok || !res.j.job) { setState(""); append("\x1b[31m" + (res.j.error || "failed") + "\x1b[0m\n"); return; }
        job = res.j.job;
        document.getElementById("runkill").disabled = false;
        setState("running…");
        es = new EventSource("/api/term/stream?job=" + encodeURIComponent(job));
        es.onmessage = function (ev) { try { append(JSON.parse(ev.data).b); } catch (e) { } };
        es.addEventListener("end", function (ev) {
          var d = {}; try { d = JSON.parse(ev.data); } catch (e) { }
          closeStream();
          document.getElementById("runkill").disabled = true;
          setState(d.rc === 0 ? "done" : "exit " + d.rc);
        });
        // EventSource auto-reconnects on a dropped stream; a reconnect would re-stream the whole
        // job forever, so close on error instead.
        es.onerror = function () { closeStream(); document.getElementById("runkill").disabled = true; setState("disconnected"); };
      }).catch(function () { setState("failed"); });
  }
  function stop() {
    if (!job) return;
    fetch("/api/term/kill", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job: job })
    }).catch(function () { });
  }

  EXT.push(function (d) {
    if (enabled === false) return;
    if (enabled === null) {                 // one probe: a 403 means the feature is off, so the
      enabled = "pending";                  // panel never appears rather than appearing dead
      fetch("/api/term/status").then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          enabled = !!j;
          if (!enabled) { host.innerHTML = ""; return; }
          if (!built) build();
          document.getElementById("runhint").textContent =
            "no shell — allowed: " + (j.allow || []).join(", ");
        }).catch(function () { enabled = false; host.innerHTML = ""; });
      return;
    }
    if (enabled !== true) return;
    if (!built) build();
    var m = d.meta || {};
    sid = (typeof cur === "string" ? cur : "");
    if (m.cwd !== cwd) {                    // session switched: the old job's output is not ours
      cwd = m.cwd || "";
      closeStream(); job = null;
      var pane = document.getElementById("runout"); if (pane) pane.innerHTML = "";
      setState("");
      var k = document.getElementById("runkill"); if (k) k.disabled = true;
    }
    var c = document.getElementById("runcard");
    if (c) c.title = cwd ? "runs in " + cwd : "no working directory for this session";
  });
})();
