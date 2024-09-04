# Security Considerations

Before you start using this tool, please consider the following:

## `--shell-escape`

We are aware that the `--shell-escape` option used when compiling TeX documents can pose a security risk. This option allows the TeX compiler to execute arbitrary shell commands, which can be exploited by malicious actors. This is sadly still necessary for some packages to work properly, such as `minted` used for syntax highlighting.

To mitigate this risk while using **untrusted templates**, we provide a sandboxed environment through a **Docker** image. This allows you to use the tool in a controlled manner.

Additionally, if you are using templates from untrusted sources, it is crucial to *thoroughly review* them for any potential malicious code before incorporating them into your workflow.

## Write access to settings file

The global [settings](../concepts/settings.md) file contains the commands that are executed during the rendering process. It is important to note that if an attacker gains write access to this file, they can execute arbitrary commands on your machine, potentially compromising its security.

For standard installations, this should not be a concern.


*Please let us know if you have any further questions or concerns.*
