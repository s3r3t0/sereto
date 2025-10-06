Type "sereto config targets add"
Enter

# Category selection screen
Wait+Screen /Category:/
Tab
Enter

# Target name
Type "Example target"
Enter

# Add locator to target JSON in vim
Type "/locators"
Enter
Type "f[a"
Enter 2
Type "  "
Escape
Type "kI    "
Type `"https://example.com/"`
Escape
Type ":wq"
Enter
Wait