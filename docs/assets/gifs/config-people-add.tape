Output config-people-add.gif
Set Height 600
Source includes/style.tape

Hide
Source includes/create-project.tape
Show

Type "sereto config people add"
Enter

# Person type selection
Wait+Screen /Select value/
Sleep 500ms
Down
Sleep 500ms
Enter
Sleep 500ms
Tab
Sleep 500ms
Enter

# Person details
Wait /Name:/
Sleep 500ms
Type "John Smith"
Enter

Wait /Business unit:/
Sleep 500ms
Type "Development"
Enter

Wait /Email:/
Sleep 500ms
Type "john.smith@example.com"
Enter

Wait /Role:/
Sleep 500ms
Type "Product Owner"
Enter

Sleep 500ms
Type "sereto config people show"
Enter
Wait

Sleep 3s