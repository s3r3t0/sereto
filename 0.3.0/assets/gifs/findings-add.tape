Output findings-add.gif
Set Height 1000
Source includes/style.tape

Hide
Source includes/create-project.tape
Source includes/add-target.tape
Type "clear"
Enter
Show

Type "sereto findings add"
Enter

# Finding TUI
Wait+Screen /Type to search.../
Sleep 2
Type@0.1 "test"
Sleep 1
Tab
Sleep 1

# Uncheck some categories
Down
Sleep 0.5
Enter
Sleep 0.5
Down@0.5 2
Sleep 1
Enter

# Select finding
Tab
Sleep 2
Enter

Wait+Screen /Finding preview/
Sleep 2
Down@0.3 10  # Scroll through finding
Sleep 2
Type "a"
Sleep 1
Tab

# Fill finding details
Type "Remote code execution"  # Name
Sleep 1
Tab
Sleep 0.5
Down@1 2  # Choose category
Enter
Tab
Sleep 1
Enter@1 2  # Choose target
Sleep 1

# Add images
Tab
Sleep 0.5
Enter
Sleep 1
Shift+Tab
Sleep 0.5
Shift+Tab
Sleep 0.5
Type@0.1 "image1.png"
Sleep 1
Tab@0.5 2
Sleep 0.5
Enter
Sleep 1
Shift+Tab
Sleep 0.5
Shift+Tab
Sleep 0.5
Type@0.1 "image2.png"
Sleep 1
Tab@0.5 3
Sleep 1
Enter
#Wait+Screen /Finding successfuly added/
Sleep 3  # Wait for finding added
Ctrl+q
Wait
Sleep 1
Type "sereto findings show"
Enter
Wait
Sleep 3