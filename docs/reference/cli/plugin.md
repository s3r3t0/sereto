# Package Plugins

::: sereto.cli.plugin

## Managed commands

Installed plugin command leaves are registered from validated cached manifests after core and legacy commands.
Startup and help do not execute plugin code. Invocation starts the active plugin generation through the authenticated
local protocol, forwards plugin arguments as `arguments.argv`, and passes the host-selected target through
`sereto.target.v1`. Use `--sereto-target SELECTOR` to select that target.

Core and legacy collisions, duplicate managed paths, invalid parent groups, and unsafe cached help text cause only the
managed command to be skipped. `sereto plugin doctor` reports the reason.
