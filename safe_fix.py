#!/usr/bin/env python3
"""Carefully apply fixes to ext_cr_boot.js line by line."""

with open('aitracker/web/ext_cr_boot.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

output = []
i = 0

while i < len(lines):
    line = lines[i]

    # 1. After line 37 (var bus = {};), add currentJob variable
    if i == 36 and line.strip() == "var bus = {};":
        output.append(line)
        output.append("  var currentJob = null;  // Track running command job id for cr:stop\n")
        i += 1
        continue

    # 2. In cr:run-command, after "emit('notify', { text: 'Running: ' + argv });"
    #    add "currentJob = res.j.job;"
    if "emit('notify', { text: 'Running: ' + argv });" in line and i > 500 and i < 600:
        output.append(line)
        output.append("      currentJob = res.j.job;\n")
        i += 1
        continue

    # 3. In the 'end' event handler, after "es.close();" add "currentJob = null;"
    if "es.close();" in line and i > 570 and i < 600 and (i == len(lines)-1 or "addEventListener('end'" in lines[i-5:i+1].__str__()):
        output.append(line)
        # Check if next non-empty line is emit notify
        j = i + 1
        while j < len(lines) and lines[j].strip() == "":
            j += 1
        if j < len(lines) and "emit('notify'" in lines[j]:
            output.append("        currentJob = null;\n")
        i += 1
        continue

    # 4. Fix error handler "es.onerror = function () { es.close(); };"
    if "es.onerror = function () { es.close(); };" in line:
        output.append(line.replace("es.onerror = function () { es.close(); };",
                                  "es.onerror = function () { es.close(); currentJob = null; };"))
        i += 1
        continue

    # 5. Replace cr:stop handler
    if "on('cr:stop'" in line and i > 660:
        # Skip old handler until closing });
        while i < len(lines) and not lines[i].strip().endswith('});'):
            i += 1
        i += 1  # Skip the closing });

        # Now add new handler
        output.append("  on('cr:stop', function (payload) {\n")
        output.append("    if (!currentJob) return;\n")
        output.append("    fetch('/api/term/kill', {\n")
        output.append("      method: 'POST', headers: { 'Content-Type': 'application/json' },\n")
        output.append("      body: JSON.stringify({ job: currentJob })\n")
        output.append("    }).catch(function () { });\n")
        output.append("  });\n")
        output.append("\n")
        continue

    output.append(line)
    i += 1

with open('aitracker/web/ext_cr_boot.js', 'w', encoding='utf-8') as f:
    f.writelines(output)

print("Applied fixes carefully")
