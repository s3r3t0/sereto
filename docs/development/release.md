# Release

1. Update the version in `pyproject.toml`
2. Update the changelog in `CHANGELOG.md`
    - Add a new section for the new version below the "Unreleased" section
    - At the bottom of the changelog, update the comparison link for the "Unreleased" and new versions
3. Generate new `uv.lock` file with `uv lock`
4. With the changes, create commit with message "Bump SeReTo version to x.y.z"
5. Create a new tag with `git tag vx.y.z`
