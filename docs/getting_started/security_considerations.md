# Security Considerations

Before you start using this tool, please consider the following:

## Write access to settings file

The global [settings](../concepts/settings.md) file contains the commands that are executed during the rendering process. It is important to note that if an attacker gains write access to this file, they can execute arbitrary commands on your machine, potentially compromising its security.

For standard installations, this should not be a concern.

## Package plugins

Install package plugins only from sources you trust. SeReTo isolates each plugin's Python dependencies in a managed
environment, but this is not an operating-system sandbox. Package build backends can execute during installation, and
plugin code executes with the same user permissions as SeReTo when its manifest or an operation is invoked.

SeReTo rejects credentials embedded in package source and index URLs. Supply private-index credentials through uv's
named-index environment variables or keyring provider instead.


*Please let us know if you have any further questions or concerns.*
