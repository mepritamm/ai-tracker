#!/usr/bin/env python3
"""Apply all fixes using simple string replacements with smart quote handling."""

with open('aitracker/web/ext_cr_boot.js', 'rb') as f:
    content_bytes = f.read()

# Convert to string for processing
content = content_bytes.decode('utf-8')

# Step 1: Add currentJob variable after "var bus = {};"
if 'var bus = {};' in content:
    content = content.replace(
        'var bus = {};\n  function on(name, fn) {',
        'var bus = {};\n  var currentJob = null;  // Track running command job id for cr:stop\n  function on(name, fn) {'
    )
    print("✓ Step 1: Added currentJob variable")

# Step 2: Track job when starting a command
if "emit('notify', { text: 'Running: ' + argv });" in content:
    content = content.replace(
        "      emit('notify', { text: 'Running: ' + argv });\n      if (typeof EventSource !== 'function') return;",
        "      emit('notify', { text: 'Running: ' + argv });\n      currentJob = res.j.job;\n      if (typeof EventSource !== 'function') return;"
    )
    print("✓ Step 2: Track job at start")

# Step 3: Clear job when stream ends
if "es.close();\n        emit('notify'" in content:
    # Need to handle the em-dash in the template literal
    # Search for a pattern that's more flexible
    import re
    pattern = r"es\.close\(\);\n(\s+)emit\('notify'.*?argv.*?\)"
    def replace_close(match):
        indent = match.group(1)
        return f"es.close();\n{indent}currentJob = null;\n{indent}emit('notify', {{ text: argv + (d.rc === 0 ? ' — done' : ' — exit ' + d.rc) }});"
    # This is complex, let's try a simpler approach
    if "es.close();\n        emit('notify'" in content:
        idx = content.find("es.close();\n        emit('notify'")
        if idx >= 0:
            # Find the end of the emit statement
            end_idx = content.find(";\n", idx) + 2
            old = content[idx:end_idx]
            new = old.replace("es.close();", "es.close();\n        currentJob = null;")
            content = content[:idx] + new + content[end_idx:]
            print("✓ Step 3: Clear job on stream end")

# Step 4: Clear job on error
if "es.onerror = function () { es.close(); };" in content:
    content = content.replace(
        "es.onerror = function () { es.close(); };",
        "es.onerror = function () { es.close(); currentJob = null; };"
    )
    print("✓ Step 4: Clear job on error")

# Step 5: Replace cr:stop handler using regex to handle smart quotes
import re
# Match from on('cr:stop' to closing });
# This needs to be flexible about quotes
pattern = r"  // Stop.*?\n  on\('cr:stop'.*?\n  \}\);"
match = re.search(pattern, content, re.DOTALL)
if match:
    old_handler = match.group(0)
    new_handler = """  // Stop — stops the currently-running command (via the same /api/term/kill
  // endpoint ext_run.js's stop() already uses). Mirrors ext_run.js's behaviour:
  // only executes if a job is actually running; silently returns otherwise.
  on('cr:stop', function (payload) {
    if (!currentJob) return;
    fetch('/api/term/kill', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job: currentJob })
    }).catch(function () { });
  });"""
    content = content.replace(old_handler, new_handler)
    print("✓ Step 5: Replaced cr:stop handler")
else:
    print("✗ Step 5: Could not find cr:stop handler to replace")

with open('aitracker/web/ext_cr_boot.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("\nDone!")
