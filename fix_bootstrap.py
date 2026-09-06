#!/usr/bin/env python3
# Fix ext_cr_boot.js - add currentJob tracking and wire up cr:stop

with open('aitracker/web/ext_cr_boot.js', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add currentJob variable after "var bus = {};"
content = content.replace(
    "var bus = {};",
    "var bus = {};\n  var currentJob = null;  // Track running command job id for cr:stop"
)

# 2. In cr:run-command, after "emit('notify', { text: 'Running: ' + argv });"
# add "currentJob = res.j.job;"
content = content.replace(
    "      emit('notify', { text: 'Running: ' + argv });\n      if (typeof EventSource !== 'function') return;",
    "      emit('notify', { text: 'Running: ' + argv });\n      currentJob = res.j.job;\n      if (typeof EventSource !== 'function') return;"
)

# 3. In the 'end' event handler, after "es.close();" add "currentJob = null;"
content = content.replace(
    "        es.close();\n        emit('notify', { text: argv + (d.rc === 0 ? ' — done' : ' — exit ' + d.rc) });",
    "        es.close();\n        currentJob = null;\n        emit('notify', { text: argv + (d.rc === 0 ? ' — done' : ' — exit ' + d.rc) });"
)

# 4. Fix the error handler
content = content.replace(
    "      es.onerror = function () { es.close(); };",
    "      es.onerror = function () { es.close(); currentJob = null; };"
)

# 5. Replace the entire cr:stop handler
old_stop = """  // Stop — REQUIRED ADDITION, not wired: there is no server route that stops
  // "whatever this session is doing" as a general action. The only kill-style
  // routes that exist are POST /api/term/kill (needs a `job` id from a run
  // this file itself just started — see cr:run-command above, not a bare
  // sessionId) and POST /api/term/close (needs a `tty` id). Neither can be
  // reached from just {sessionId}. Left disabled at the source in
  // ext_cr_detail.js (the phone-bar Stop button carries `disabled` + a title
  // explaining why) rather than wired to an endpoint that doesn't answer the
  // actual question asked.
  on('cr:stop', function () {
    emit('notify', { text: 'Stopping a session isn't supported yet — there's no server route for it.' });
  });"""

new_stop = """  // Stop — stops the currently-running command (via the same /api/term/kill
  // endpoint ext_run.js's stop() already uses). Mirrors ext_run.js's behaviour:
  // only executes if a job is actually running; silently returns otherwise.
  on('cr:stop', function (payload) {
    if (!currentJob) return;
    fetch('/api/term/kill', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job: currentJob })
    }).catch(function () { });
  });"""

content = content.replace(old_stop, new_stop)

with open('aitracker/web/ext_cr_boot.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("Successfully applied all fixes to ext_cr_boot.js")
