# Security Reporting Tool

<!-- Badges -->
[![Documentation](https://img.shields.io/badge/Documentation-SeReTo-blue)](https://sereto.s4n.cz/)
[![PyPI](https://img.shields.io/pypi/v/sereto?label=PyPI)](https://pypi.org/project/sereto/)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/s3r3t0/sereto/main/docs/assets/logo/sereto_block_white.svg">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/s3r3t0/sereto/main/docs/assets/logo/sereto_block_black.svg">
  <img alt="SeReTo logo" src="https://raw.githubusercontent.com/s3r3t0/sereto/main/docs/assets/logo/sereto_block_black.svg" height="300">
</picture>

## Getting Started

Install SeReTo using `uv`, which creates an isolated environment for the tool and its dependencies:

```bash
uv tool install sereto@latest --with-requirements <path>/templates/requirements.txt
```

This command installs SeReTo along with all template dependencies, ensuring that custom plugins and templates work correctly. You can specify a version (e.g., `sereto@x.y.z`) or use `@latest` for the newest release.

For detailed setup instructions, visit the [documentation](https://sereto.s4n.cz/latest/getting_started/installation/).

> Created with support of [NN Management Services, s.r.o.](https://www.nn.cz/kariera/en/nn-digital-hub/)
