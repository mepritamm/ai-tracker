#!/usr/bin/env python3
# Fix ext_cr_boot.js - specifically replace the cr:stop handler

with open('aitracker/web/ext_cr_boot.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find and replace the cr:stop handler - find the line with on('cr:stop' or on("cr:stop"
# and replace everything until the closing });

output = []
i = 0
while i < len(lines):
    line = lines[i]

    # Check if this is the start of the cr:stop handler
    if "on('cr:stop'" in line or 'on("cr:stop"' in line:
        # Skip the old handler until we find the closing });
        # But first, output the comment lines before it
        j = i - 1
        comment_lines = []
        while j >= 0 and '//' in lines[j]:
            comment_lines.insert(0, lines[j])
            j -= 1

        # Output new handler with proper comments and code
        output.append("  // Stop — stops the currently-running command (via the same /api/term/kill\n")
        output.append("  // endpoint ext_run.js's stop() already uses). Mirrors ext_run.js's behaviour:\n")
        output.append("  // only executes if a job is actually running; silently returns otherwise.\n")
        output.append("  on('cr:stop', function (payload) {\n")
        output.append("    if (!currentJob) return;\n")
        output.append("    fetch('/api/term/kill', {\n")
        output.append("      method: 'POST', headers: { 'Content-Type': 'application/json' },\n")
        output.append("      body: JSON.stringify({ job: currentJob })\n")
        output.append("    }).catch(function () { });\n")
        output.append("  });\n")

        # Skip the old handler lines
        i += 1
        while i < len(lines) and not lines[i].strip().endswith('});'):
            i += 1
        i += 1  # Skip the closing });
    else:
        output.append(line)
        i += 1

with open('aitracker/web/ext_cr_boot.js', 'w', encoding='utf-8') as f:
    f.writelines(output)

print("Successfully replaced cr:stop handler")
