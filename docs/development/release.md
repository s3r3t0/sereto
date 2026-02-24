# Release

The release process is automated via GitHub Actions. It consists of two workflows that handle version bumping, changelog updates, and tag creation.

## Prerequisites

- The `## [Unreleased]` section in `CHANGELOG.md` must contain at least one entry.

## Steps

1. Ensure `CHANGELOG.md` has the desired entries under `## [Unreleased]`.
2. Go to **Actions** → **Prepare Release** → **Run workflow**.
3. Select the bump type (`patch`, `minor`, or `major`) and run it.
4. The workflow creates a `release/vX.Y.Z` branch with:
    - Updated version in `pyproject.toml`
    - New version section in `CHANGELOG.md` (with today's date)
    - Updated comparison links at the bottom of `CHANGELOG.md`
    - Regenerated `uv.lock`
5. Review and merge the generated PR into `main`.
6. On merge, the **Tag Release** workflow automatically creates and pushes the `vX.Y.Z` tag.
7. The tag push triggers the existing release pipelines:
    - **PyPI** publishing (with Sigstore signing)
    - **GitHub Release** creation (with changelog body)
    - **Docker Hub** image build and push
    - **Documentation** deployment via mike
