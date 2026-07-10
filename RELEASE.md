# Releasing omem

`omem` is released by the repository's GitHub Actions workflow. Do not put a
PyPI token in files, commits, or shell history.

## Before Releasing

1. Record the version's user-visible changes in
   [CHANGELOG.md](CHANGELOG.md).
2. Run the complete test suite, build, and wheel smoke test.
3. Confirm that the target version is not already published on PyPI.
4. Configure a PyPI Trusted Publisher for this repository, or configure a
   protected `PYPI_API_TOKEN` repository secret.

## Release Flow

Run `Release Python SDK to PyPI` manually from GitHub Actions and provide the
target version. The workflow validates the version, runs tests, builds the
package, creates the tag, and publishes the release.

If publication fails after the tag was created, rerun the workflow in publish
resume mode with the same version. Resume mode revalidates the code and build
artifacts for that tag; it does not create another tag.

After the release completes, install that version from PyPI in a fresh virtual
environment and import `Memory`.
