# SeReTo (Security Reporting Tool)

Python CLI/TUI for penetration testers that generates security assessment reports as PDF. Each project is a directory provisioned from templates. Document templates (reports, statements of work, etc.) are XeLaTeX or Typst. Findings are Markdown with TOML frontmatter, which Pandoc converts to XeLaTeX/Typst during rendering.

## Commands

- Verify (run before finishing any change): `tox -e lint,type,ty,pre-commit,py312`. If `tox` is not installed, use `uvx tox`.
- Format: `tox -e format`
- Single test: `python -m pytest tests/<path>::<name>`

All checks must pass. Don't silence type or lint errors unless there is no other fix.

## Layout

- `sereto/cli/`: Click commands (entry point: `sereto.cli.cli:entry_point`)
- `sereto/tui/`: Textual UI
- `sereto/models/`: Pydantic models (config, settings, findings, targets)
- `sereto/exceptions.py`: `Sereto*Error` exceptions. Raise these, not bare built-ins.
- `tests/`: pytest, mirroring the `sereto/` layout
- `docs/`: MkDocs Material documentation

## Conventions

- Python 3.12+, with full type hints checked by mypy and ty except in tests. Validate data with Pydantic models; public functions usually use `@validate_call`.
- Add or update tests for every behavior change.
- Record user-visible changes in `CHANGELOG.md` under `## [Unreleased]` (Keep a Changelog format).
- Jinja2 delimiters:
  - Markdown templates use the defaults (`{{ }}`, `{% %}`, `{# #}`).
  - TeX/Typst templates use `((( )))` for variables, `((* *))` for blocks and `((= =))` for comments.
- Logging: `from loguru import logger`. With Rich markup, escape dynamic values: `logger.info("x {}", escape(var), markup=True)` (`escape` from `rich.markup`).

## Security

The tool handles confidential client data. Treat project files, templates, finding metadata and source archives as untrusted input.

- Subprocesses: pass an argument list and never use `shell=True`. Resolve executables with `shutil.which`.
- Paths: keep file operations inside the project root (resolve, then `is_relative_to`; see `Project.ensure_dir`). Extract tar files only with `filter="data"`.
- TeX output: HTML autoescaping is intentionally off. Escape interpolated text with the `tex` filter.
- Secrets: keep them in `SecretStr`/`SecretBytes` and get passwords through `sereto.keyring`. Never log or print secrets or report contents.
- Cryptography: use only the existing `sereto.crypto` primitives (AES-GCM, Argon2id). Never implement custom crypto and never reuse nonces or salts.
- Ruff `S` (bandit) rules are enforced. Fix findings rather than suppressing them. For a genuine false positive, add `# noqa: S<code>` with a justifying comment.

## References

- Project files: `docs/concepts/project_files.md`
- Settings: `docs/concepts/settings.md`
- Usage: `docs/usage.md`
- Security model: `docs/getting_started/security_considerations.md`
