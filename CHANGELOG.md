# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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


[unreleased]: https://github.com/s3r3t0/sereto/compare/v0.0.6...HEAD
[0.0.6]: https://github.com/s3r3t0/sereto/compare/v0.0.5...v0.0.6
[0.0.5]: https://github.com/s3r3t0/sereto/compare/v0.0.4...v0.0.5
[0.0.4]: https://github.com/s3r3t0/sereto/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/s3r3t0/sereto/releases/tag/v0.0.3
