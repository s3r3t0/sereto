# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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


[unreleased]: https://github.com/s3r3t0/sereto/compare/v0.0.10...HEAD
[0.0.10]: https://github.com/s3r3t0/sereto/compare/v0.0.9...v0.0.10
[0.0.9]: https://github.com/s3r3t0/sereto/compare/v0.0.8...v0.0.9
[0.0.8]: https://github.com/s3r3t0/sereto/compare/v0.0.7...v0.0.8
[0.0.7]: https://github.com/s3r3t0/sereto/compare/v0.0.6...v0.0.7
[0.0.6]: https://github.com/s3r3t0/sereto/compare/v0.0.5...v0.0.6
[0.0.5]: https://github.com/s3r3t0/sereto/compare/v0.0.4...v0.0.5
[0.0.4]: https://github.com/s3r3t0/sereto/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/s3r3t0/sereto/releases/tag/v0.0.3
