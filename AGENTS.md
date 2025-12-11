# SeReTo (Security Reporting Tool)

Python utility for penetration testers that generates professional security assessment reports in PDF. For each project, it provisions a directory structure pre-populated from templates. Document templates (reports, statements of work, etc.) are available in XeLaTeX or Typst. Finding templates rely on Markdown format with TOML frontmatter, which Pandoc converts into the main document format (XeLaTeX/Typst) during rendering.

## Overview

- Modern Python 3.12+
- Type hints (except in tests) with Pydantic models for data validation
- Automatic code formatting with `tox -e format`
- Linting, type checking, and tests executed via `tox` (see `docs/development/tests.md`)
- Jinja2 templating with the delimiters defined in `docs/concepts/idea.md` under "Templating - Jinja2"

## File Structure

- `docs/`: Documentation in Material for MkDocs format
- `sereto/`: Core source code
- `sereto/cli/`: Command-line interface components
- `sereto/tui/`: Textual-based user interface components
- `sereto/models/`: Pydantic models
- `tests/`: Unit tests

## References

- Project file structure: `docs/concepts/project_files.md`
- Global settings: `docs/concepts/settings.md`
- Basic usage guide: `docs/usage.md`
