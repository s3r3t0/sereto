# Package Plugins

::: sereto.cli.plugin

Updates are staged in a separate managed generation. SeReTo validates the resolved environment and manifest before
atomically replacing the cached active record. A failed or unchanged candidate does not replace the active generation.

## Managed commands

Installed plugin command leaves are registered from validated cached manifests after core and legacy commands.
Startup and help do not execute plugin code. Invocation starts the active plugin generation through the authenticated
local protocol, forwards plugin arguments as `arguments.argv`, and passes the host-selected target through
`sereto.target.v1`. Use `--sereto-target SELECTOR` to select that target.

Core and legacy collisions, duplicate managed paths, invalid parent groups, and unsafe cached help text cause only the
managed command to be skipped. `sereto plugin doctor` reports the reason.

Managed commands validate all returned finding proposals before review. Use repeatable `--sereto-accept PROPOSAL_ID`
or `--sereto-accept-all` for explicit non-interactive acceptance. Interactive review supports accept, reject, and JSON
modification followed by one batch confirmation. Accepted findings are committed transactionally by SeReTo and include
core-owned package-plugin origin details; plugins never write project files.
