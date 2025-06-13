Output config-targets-add.gif
Set Height 700
Source includes/style.tape

Hide
Source includes/create-project.tape
Show

Type "sereto config targets add"
Enter

# Category selection screen
Wait+Screen /Category:/
Sleep 1s
Tab
Sleep 1s
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
Type `"https://example.com/"`
Escape
Type ":wq"
Sleep 2s
Enter
Sleep 500ms

Type "sereto config targets show"
Enter

Sleep 3s