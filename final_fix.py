#!/usr/bin/env python3
"""Apply all fixes using simple string replacements."""

with open('aitracker/web/ext_cr_boot.js', 'r', encoding='utf-8') as f:
    content = f.read()

# Step 1: Add currentJob variable after "var bus = {};"
content = content.replace(
    'var bus = {};\n  function on(name, fn) {',
    'var bus = {};\n  var currentJob = null;  // Track running command job id for cr:stop\n  function on(name, fn) {'
)

# Step 2: Track job when starting a command
content = content.replace(
    "      emit('notify', { text: 'Running: ' + argv });\n      if (typeof EventSource !== 'function') return;",
    "      emit('notify', { text: 'Running: ' + argv });\n      currentJob = res.j.job;\n      if (typeof EventSource !== 'function') return;"
)

# Step 3: Clear job when stream ends
content = content.replace(
    "        es.close();\n        emit('notify', { text: argv + (d.rc === 0 ? ' — done' : ' — exit ' + d.rc) });",
    "        es.close();\n        currentJob = null;\n        emit('notify', { text: argv + (d.rc === 0 ? ' — done' : ' — exit ' + d.rc) });"
)

# Step 4: Clear job on error
content = content.replace(
    "      es.onerror = function () { es.close(); };",
    "      es.onerror = function () { es.close(); currentJob = null; };"
)

# Step 5: Replace entire cr:stop handler (the comment block + the handler)
# Find the section from "// Stop — REQUIRED ADDITION" to "});" (the one that closes the on() call)
old_stop_section = """  // Stop — REQUIRED ADDITION, not wired: there is no server route that stops
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

new_stop_section = """  // Stop — stops the currently-running command (via the same /api/term/kill
  // endpoint ext_run.js's stop() already uses). Mirrors ext_run.js's behaviour:
  // only executes if a job is actually running; silently returns otherwise.
  on('cr:stop', function (payload) {
    if (!currentJob) return;
    fetch('/api/term/kill', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job: currentJob })
    }).catch(function () { });
  });"""

content = content.replace(old_stop_section, new_stop_section)

with open('aitracker/web/ext_cr_boot.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("Applied all fixes successfully")
