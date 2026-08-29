#!/usr/bin/env python3
import re

with open('aitracker/web/ext_cr_boot.js', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: Add currentJob variable after bus declaration
content = content.replace(
    '  var bus = {};',
    '  var bus = {};\n  var currentJob = null;  // Track running command job id for cr:stop'
)

# Fix 2: In cr:run-command, track the job
content = content.replace(
    "      emit('notify', { text: 'Running: ' + argv });\n      if (typeof EventSource !== 'function') return;",
    "      emit('notify', { text: 'Running: ' + argv });\n      currentJob = res.j.job;\n      if (typeof EventSource !== 'function') return;"
)

# Fix 3: Clear currentJob in the 'end' event handler
content = content.replace(
    "        es.close();\n        emit('notify', { text: argv + (d.rc === 0 ? ' — done' : ' — exit ' + d.rc) });",
    "        es.close();\n        currentJob = null;\n        emit('notify', { text: argv + (d.rc === 0 ? ' — done' : ' — exit ' + d.rc) });"
)

# Fix 4: Clear currentJob in error handler
content = content.replace(
    "      es.onerror = function () { es.close(); };",
    "      es.onerror = function () { es.close(); currentJob = null; };"
)

# Fix 5: Replace cr:stop handler using regex to handle smart quotes
# Match from "on('cr:stop'" to the closing "});" after it
pattern = r"  on\('cr:stop',.*?\n  \}\);"
replacement = """  on('cr:stop', function (payload) {
    if (!currentJob) return;
    fetch('/api/term/kill', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job: currentJob })
    }).catch(function () { });
  });"""

# Use dotall flag to match across lines
content = re.sub(pattern, replacement, content, flags=re.DOTALL)

with open('aitracker/web/ext_cr_boot.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("All fixes applied successfully")
