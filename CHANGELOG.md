# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Use NamedTuple to represent result of key derivation with Argon2

### Fixed

- Fix `sereto ls` failing when there is a file in the report directory (too strict argument check in `Project.is_project_dir` function).
- Fix unpacking unencrypted source archive.

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


[unreleased]: https://github.com/s3r3t0/sereto/compare/v0.0.15...HEAD
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
