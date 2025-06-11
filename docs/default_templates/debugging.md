# Debugging templates

Jinja templates can be complex, and debugging them can be challenging. This guide provides tips and techniques to help you debug your templates effectively.

Jinja contains two built-in functions that can be useful for debugging:

- `{{ debug() }}`: This function prints the current context, including all variables and their values.
- `{{ pprint(variable) }}`: This function pretty-prints a variable, making it easier to read complex data structures.

!!! tip
    The public templates include a `debug` template. This template prints all configured variables and their values. Invoke it as an alternative to the report template: `sereto pdf report --template debug`.
