Type "sereto config targets add"
Enter

# Category selection screen
Wait+Screen /Category:/
Sleep 500ms
Type "d"
Sleep 500ms
Enter
Sleep 500ms
Tab
Sleep 500ms
Enter

# Target name
Type "Example target"
Enter

# Add locator to target JSON in vim
Sleep 2s
Type "/locators"
Enter
Type "f[a"
Enter 2
Type "  "
Escape
Type "kI    "
Type `{"type": "url", "value": "https://example.com/"},`
Enter
Type `{"type": "ip", "value": "192.0.2.0", "description": "Example target IP address"}`
Escape
Type ":wq"
Sleep 2s
Enter
Sleep 500ms

Type "sereto config targets show"
Enter