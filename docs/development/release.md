# Release

The release process is automated via GitHub Actions. It handles version bumping, changelog updates, tag creation, package publishing, release signing, and reproducibility verification.

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
    - **Python package build** using a pinned build toolchain
    - **Reproducibility verification** by rebuilding the wheel and sdist and comparing hashes
    - **PyPI** publishing
    - **GitHub Release** creation with the built artifacts and Sigstore signatures attached during release creation
    - **Docker Hub** image build and push
    - **Documentation** deployment via mike

## Notes

- GitHub Releases are configured as immutable. The workflow therefore creates the release together with all assets in one operation, instead of publishing first and uploading assets afterwards.
- Python package builds are configured to be reproducible. The release workflow pins the build backend/tool versions, sets `SOURCE_DATE_EPOCH` from the tagged commit, rebuilds the distributions, and blocks publishing if the hashes differ.

## Verifying reproducibility locally

To verify that a tagged release is reproducible, build it twice from a clean checkout of the same tag and compare the hashes:

```sh
git checkout vX.Y.Z
rm -rf dist build *.egg-info

export SOURCE_DATE_EPOCH="$(git log -1 --format=%ct HEAD)"

python -m pip install --user "build==1.4.3"
python -m build
sha256sum dist/* > /tmp/sereto-build1.sha256

rm -rf dist build *.egg-info
python -m build
sha256sum dist/* > /tmp/sereto-build2.sha256

diff -u /tmp/sereto-build1.sha256 /tmp/sereto-build2.sha256
```

If the output is empty, the wheel and source distribution are bit-for-bit identical for that environment and toolchain.
