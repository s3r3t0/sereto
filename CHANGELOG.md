# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.6] - 2025-05-23

### Added

- Add locators for findings and targets.
- Specify `default_people` in settings.
- Add option to `sereto pdf report` to specify report template.

### Dependencies

- Update pypdf requirement from ~=5.4.0 to ~=5.5.0
- Update cryptography requirement from ~=44.0.0 to ~=45.0.2

## [0.2.5] - 2025-04-21

### Fixed

- Do not duplicate the `\figure` environment for images (turn off implicit figure generation)

### Removed

- Remove need for `--shell-escape` when rendering the TeX documents

### Dependencies

- Update pydantic-settings requirement from ~=2.8.0 to ~=2.9.1
- Update rapidfuzz requirement from ~=3.12.1 to ~=3.13.0
- Update textual requirement from ~=3.0.0 to ~=3.1.0

## [0.2.4] - 2025-04-05

### Added

- Add method `Config.replace_version_config`
- Configure variables from the `findings add` TUI

### Changed

- Update error messages for Jinja2 missing variables

### Fixed

- Fix mismatch in the attached source archive name when embedding the archive vs. unpacking.

## [0.2.3] - 2025-04-02

### Changed

- Validate variables for sub-findings if the corresponding template can be found.
- Print error if variable is missing for Jinja2 (optional variables now need to stricly check with `is defined`)

## [0.2.2] - 2025-04-01

### Added

- Add `py.typed` file to the package to indicate that it supports type hints.

### Changed

- Allow constructing `SeretoDate` from string with a custom format string

### Fixed

- Check if there is any target before opening TUI to add findings
- Make `load_plugins` function print name of missing plugin module

### Dependencies

- Update pypdf requirement from ~=5.3.0 to ~=5.4.0
- Update textual requirement from ~=2.1.1 to ~=3.0.0
- Update rich requirement from ~=13.9.2 to ~=14.0.0
- Update pydantic requirement from ~=2.10.1 to ~=2.11.1

## [0.2.1] - 2025-03-10

### Changed

- Add fallback keyring backend (keyring-alt) to support Docker and WSL.
- Fork `click-repl` and build release from master.

## [0.2.0] - 2025-02-26

### Added

- TUI utility for fuzzy searching and adding findings to the report (`sereto findings add`).

### Changed
- **Major refactoring**: separated runtime classes from Pydantic models to better distinguish operational logic from data loading and validation.
- The entire target subtree is now version-specific; for retests, copy the subtree from the previous version.
- Migrated from findings.yaml to findings.toml.
- Updated how risk counts are represented.
- Used more explicit function arguments.
- Revised unique name generation.
- Improved `VersionConfig.filter_dates`.
- Fixed REPL UsageError (requires removing `click-repl` 0.3.0 if installed).

## [0.1.1] - 2025-02-02

### Changed

- Docs: `uv` as preferred package manager for installation.
- `sereto findings add`: Allow adding findings from other categories.

## [0.1.0] - 2024-12-22

### Added

- Introduce plugin system for adding new commands to the CLI.
- Add CLI commands: `sereto pdf target`, `sereto pdf finding-group` to render partial reports.
- `Render`: add methods for selecting recipe

### Changed

- **Breaking:** Implement new directory structure for the project.
- **Breaking:** Rename "informational" risk to "info".
- **Breaking:** Add `version_description` attribute to `VersionConfig`.
- **Breaking:** `ConvertRecipe` now has in addition to input_format also output_format.
- Command `sereto pdf report` no longer renders the partial reports.

### Fixed

- Fix target index in `delete_targets_config`
- Set correct indexes for partials (target, finding group)
- Fix path to template when reading metadata
- Fix the issue with internal links inside PDF being broken after running `embed_source_archive`

### Removed

- Remove `argon2-cffi` dependency. This was added to the `crytography` library in version 44.0.0.

## [0.0.17] - 2024-11-29

### Added

- Docs: Markdown building blocks (writing findings and their templates).
- Jinja2: add debug extension to generic env.
- REPL: Add `exit` command + `debug` command to toggle debug mode. Show debug mode indicator in the prompt.

### Changed

- **Breaking:** Modify the structure of `config.json`.
- Update REPL to use `click-repl`.
- Remove redundancy in Jinja2 rendering.
- Adjust variables passed when rendering Jinja templates.
- Use `prompt_toolkit` for user input.
- Make the default TeX rendering less verbose + fail early.
- Remove command output during rendering. We might still need to show the errors in the future.
- Display command execution time.
- `Config.filter_*` methods now contain parameter `invert`, which allows to invert the filtering logic.
- Avoid overriding TeX files if the content was not changed. This should speed up the rendering process as `latexmk` uses the file modification time to decide whether to recompile the document.

### Fixed

- Fix `Config.filter_*` methods to handle correctly None values.

## [0.0.16] - 2024-10-28

### Added

- Provide helper methods to `VersionConfig` for writing the templates - `filter_targets`, `filter_dates`, and `filter_people`
- Docs: start documenting available building blocks for writing the templates

### Changed

- Use NamedTuple to represent result of key derivation with Argon2
- Use Pydantic's Secret types when dealing with passwords. This prevents the data from being printed in the logs and tracebacks.
- Rename `BaseConfig` class to `VersionConfig`
- Implement `__str__` method for `Date` class
- Make sure the source archive always starts with the directory equal to the project ID, even if the user renamed the directory
- Handle more edge cases when extracting the source archive

### Fixed

- Fix `sereto ls` failing when there is a file in the report directory (too strict argument check in `Project.is_project_dir` function).
- Fix unpacking unencrypted source archive.

### Security

- Use filter [data](https://docs.python.org/3/library/tarfile.html#tarfile.data_filter) when extracting the source archive from tar. This takes care of the following:
    - Strip leading slashes (`/` and `os.sep`) from filenames.
    - Refuse to extract files with absolute paths (in case the name is absolute even after stripping slashes, e.g. `C:/foo` on Windows).
    - Refuse to extract files whose absolute path (after following symlinks) would end up outside the destination.
    - Clear high mode bits (setuid, setgid, sticky) and group/other write bits (`S_IWGRP` | `S_IWOTH`).
    - Refuse to extract links (hard or soft) that link to absolute paths, or ones that link outside the destination.
    - Refuse to extract device files (including pipes).
    - For regular files, including hard links:
        - Set the owner read and write permissions (`S_IRUSR` | `S_IWUSR`).
        - Remove the group & other executable permission (`S_IXGRP` | `S_IXOTH`) if the owner doesn’t have it (`S_IXUSR`).
    - For other files (directories), set `mode` to `None`, so that extraction methods skip applying permission bits.
    - Set user and group info (`uid`, `gid`, `uname`, `gname`) to `None`, so that extraction methods skip setting it.

## [0.0.15] - 2024-10-21

### Changed

- Use `TypeAdapter` instead of `RootModel` in config module.
- Type hints: start using Self
- README: rebranding IT Hub -> Digital Hub
- Improve error message for `Config` and `Settings` validation
- Prefer annotated types over `Field`
- Use more `DirectoryPath` and `FilePath` instead of plain `Path`
- Apply args validation for more function (`@validate_call`)
- Refactor: `Config.from_file` -> `Config.load_from`
- Refactor: `Settings.from_file` -> `Settings.load_from`
- Refactor: `FindingsConfig.from_yaml_file` -> `FindingsConfig.from_yaml`
- Refactor: fn `write_conifg` -> `Config.dump_json`
- Refactor class `Report` to `Project`, which now contains also `settings` and `path` attributes
- Refactor: `Project.load_runtime_vars` -> `Config.update_paths`
- Refactor: `Project.is_report_dir` -> `Project.is_project_dir`
- Refactor: fn `extract_source_archive` -> `retrieve_source_archive`
- Refactor: fn `untar_sources` -> `extract_source_archive`
- Move `config` module into `cli`, as it contains only CLI related functions
- Reflect changes in the documentation

### Removed

- Remove artefacts of `sereto.cli.console`
- Remove module `cleanup`
- Remove unused functions `get_all_projects`, `get_all_projects_dict`, and `is_settings_valid`

## [0.0.14] - 2024-10-18

### Changed

- Code refactoring and cleanup, mainly around source archive handling.
- Validate password retrieved from system keyring against `TypePassword` type.
- Clarify fn usage: `Report.get_path` -> `Report.get_path_from_cwd`.

### Fixed

- `sereto unpack` can now properly handle extracting encrypted or unencrypted archives.

## [0.0.13] - 2024-10-09

### Changed

- Improve REPL and use it as the default command for Docker image.
- Code cleanup: docstrings; move `Console` class to `sereto.cli.utils` module and `handle_exceptions` decorator to `sereto.exceptions`.
- Docs: enable privacy plugin.
- Docs: Set CSP and Referrer-Policy headers through the meta tag.

### Removed

- Remove support for Python 3.10.

## [0.0.12] - 2024-09-27

### Added

- Add a new command `sereto decrypt` to extract the project sources from `source.sereto` file.
- Add a new command `sereto unpack` to extract the project sources from a report's PDF file.

### Changed

- Keyring: change the location, as the username should not be empty.
- Bump version of keyring and pypdf

## [0.0.11] - 2024-09-20

### Added

- Encrypt the attached source archive

### Changed

- Docker: use version as tag, format default settings.json
- CI/CD: Fix invalid `${{ github.ref_name#v }}` syntax

## [0.0.10] - 2024-09-20

### Changed

- Implement REPL (Read-Eval-Print-Loop) for the CLI.
- Extract only relevant part of the changelog into GH release.
- Docs: Update installation instructions related to Docker and DockerHub.
- Adjust Dependabot to use `versioning-strategy: "increase"`.

## [0.0.9] - 2024-09-08

### Changed

- CI/CD: Try to fix Docker pipeline.
- CI/CD: Add checkout action to make the CHANGELOG.md file available.

## [0.0.8] - 2024-09-08

### Added

- CI/CD: Build and push Docker image to Docker Hub.

### Changed

- Include notes from CHANGELOG.md into GH release notes.

## [0.0.7] - 2024-09-07

### Added

- Tests: Add tests for the `sereto new` command.
- Docs: Add section about `sereto.cli.cli`, and `sereto.types` to references.

### Changed

- README: Add PyPI badge, fix link to the installation section in the documentation.
- Docs: Updated the *Usage* section, especially part "Create Report".
- Define annotated types in separate file.

### Fixed

- CI/CD: Add CNAME file to stop overwriting the custom domain in the GitHub Pages deployment.

## [0.0.6] - 2024-09-04

### Added

- Define a security policy in SECURITY.md file.
- Docs: Add security considerations to the documentation.

### Changed

- Docker: Update Dockerfile to use low privileged user for running the application.
- README: Getting started section, mainly pointing to the documentation.

## [0.0.5] - 2024-09-04

### Changed

- CI/CD: Don't upload the package to TestPyPI, pushing the same version again makes the pipeline fail.
- README: Use different image for dark / light mode. Hopefully this will not break the PyPI rendering.
- README: Add badge with a link to the documentation.
- Docs: Move development instructions from README to the documentation.

### Fixed

- Docs: Adjust link since original content from `report_structure.md` was moved to `project_files.md`.

## [0.0.4] - 2024-09-03

- Update image in README.md to absolute URL. This is necessary for the PyPI to render the image correctly.
- Add pipeline for building
- Update docs

## 0.0.2, [0.0.3] - 2024-09-02

We registered a dummy package to PyPI to test the publishing. Therefore a version increment was necessary.

## 0.0.1

Initial version


[unreleased]: https://github.com/s3r3t0/sereto/compare/v0.2.6...HEAD
[0.2.6]: https://github.com/s3r3t0/sereto/compare/v0.2.5...v0.2.6
[0.2.5]: https://github.com/s3r3t0/sereto/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/s3r3t0/sereto/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/s3r3t0/sereto/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/s3r3t0/sereto/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/s3r3t0/sereto/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/s3r3t0/sereto/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/s3r3t0/sereto/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/s3r3t0/sereto/compare/v0.0.17...v0.1.0
[0.0.17]: https://github.com/s3r3t0/sereto/compare/v0.0.16...v0.0.17
[0.0.16]: https://github.com/s3r3t0/sereto/compare/v0.0.15...v0.0.16
[0.0.15]: https://github.com/s3r3t0/sereto/compare/v0.0.14...v0.0.15
[0.0.14]: https://github.com/s3r3t0/sereto/compare/v0.0.13...v0.0.14
[0.0.13]: https://github.com/s3r3t0/sereto/compare/v0.0.12...v0.0.13
[0.0.12]: https://github.com/s3r3t0/sereto/compare/v0.0.11...v0.0.12
[0.0.11]: https://github.com/s3r3t0/sereto/compare/v0.0.10...v0.0.11
[0.0.10]: https://github.com/s3r3t0/sereto/compare/v0.0.9...v0.0.10
[0.0.9]: https://github.com/s3r3t0/sereto/compare/v0.0.8...v0.0.9
[0.0.8]: https://github.com/s3r3t0/sereto/compare/v0.0.7...v0.0.8
[0.0.7]: https://github.com/s3r3t0/sereto/compare/v0.0.6...v0.0.7
[0.0.6]: https://github.com/s3r3t0/sereto/compare/v0.0.5...v0.0.6
[0.0.5]: https://github.com/s3r3t0/sereto/compare/v0.0.4...v0.0.5
[0.0.4]: https://github.com/s3r3t0/sereto/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/s3r3t0/sereto/releases/tag/v0.0.3
