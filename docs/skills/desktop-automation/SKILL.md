---
name: desktop-automation
description: Interact with the desktop environment — send notifications, read/write clipboard, open files, monitor system resources, and automate repetitive OS tasks
version: "1.0"
trigger_keywords:
  - notify
  - notification
  - clipboard
  - copy
  - paste
  - open file
  - system info
  - cpu
  - ram
  - memory usage
  - desktop
  - alert
tools_required:
  - notify
  - clipboard_read
  - clipboard_write
  - open_file
  - system_info
  - run_shell
---

# Desktop Automation and System Integration

MagAgent can interact with the desktop environment through dedicated tools.

## Desktop Notifications

Send a notification when a long task completes:

```
# After a long build or analysis completes:
notify("Build Complete ✓", "Your project compiled successfully in 42s")

# Alert on error
notify("Test Failed ✗", "3 tests failed in test_auth.py", urgency="critical")

# Reminder
notify("MagAgent", "Don't forget to commit your changes before standup!")
```

Urgency levels: `low`, `normal`, `critical`

## Clipboard Integration

```
# Read what's in the clipboard (great for "fix this code" workflows)
clipboard_read()
# Returns: {"ok": true, "content": "def broken_function():\n    ...", "length": 234}

# Write results to clipboard so user can paste anywhere
clipboard_write("SELECT * FROM users WHERE active = 1 ORDER BY created_at DESC;")
# Agent can then say: "I've copied the SQL query to your clipboard"
```

**Powerful pattern:** User copies code → asks "fix this" → agent reads clipboard → fixes it → writes result back to clipboard.

## Open Files in Default Application

```
# Open a generated report in the default PDF viewer
open_file("reports/q3_report.pdf")

# Open a spreadsheet in LibreOffice/Excel
open_file("analysis/sales_data.xlsx")

# Open a generated Word document
open_file("letters/client_letter.docx")
```

## System Information

```
# Check system health before a large task
system_info()
```

Returns:
```json
{
  "cpu_percent": 23.5,
  "ram_total_gb": 32.0,
  "ram_used_gb": 18.4,
  "ram_percent": 57.5,
  "disk_total_gb": 500.0,
  "disk_free_gb": 234.1,
  "platform": "linux",
  "python": "3.11.2"
}
```

Use this to:
- Check available disk before large file operations
- Warn if RAM is low before loading large datasets
- Confirm Python version for compatibility checks

## Automation Patterns

### "Fix this and put it back" workflow
```
1. clipboard_read()          → get user's code
2. Process/fix the code
3. clipboard_write(fixed)    → put back in clipboard
4. notify("Done", "Fixed code is in your clipboard")
```

### "Generate and open" workflow
```
1. Generate a PDF/spreadsheet/document
2. open_file("output.pdf")   → immediately opens in viewer
3. notify("Report Ready", "Your Q3 report is open")
```

### Resource-aware task planning
```
1. info = system_info()
2. if info["ram_percent"] > 90:
       "Warning: RAM at 90%, loading large dataset may be slow"
3. if info["disk_free_gb"] < 2:
       "Warning: Less than 2GB disk free"
```

## Shell-Based Automation

For tasks not covered by built-in tools:

```bash
# Find and kill a process by name
run_shell("pkill -f 'dev_server.py'")

# Open a URL in the browser
run_shell("xdg-open https://docs.python.org")

# Take a screenshot (requires scrot or gnome-screenshot)
run_shell("scrot -d 2 screenshot.png")

# Watch a directory for changes
run_shell("inotifywait -m -e create,modify ./src")
```
