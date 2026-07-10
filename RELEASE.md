# Releasing MemAura

`memaura` is released only through the repository's GitHub Actions workflow.
The workflow uses PyPI Trusted Publishing; do not create, store, or commit a
PyPI API token for this project.

## Before Releasing

1. Record the version's user-visible changes in [CHANGELOG.md](CHANGELOG.md).
2. Confirm that the target version is not already published on PyPI.
3. Configure the repository as a PyPI Trusted Publisher and protect the `pypi`
   GitHub Actions environment.

## Release Flow

Run `Release MemAura to PyPI` manually from GitHub Actions and provide the
target version. A normal release validates the PEP 440 version, runs tests,
builds and checks artifacts, creates an annotated tag, pushes it, and publishes
through OIDC.

If publication fails after the tag has been created, run the same workflow with
the version and `resume_publish` enabled. Resume mode checks out and verifies
the existing tag, then only retries publication. It never changes the tag or
creates an additional release commit.

After publication, install the version from PyPI in a new virtual environment
and import `Memory` from `memaura`.
