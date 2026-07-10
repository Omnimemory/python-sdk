# Contributing to omem

Thanks for improving the OmniMemory Python SDK.

## Development Setup

Use Python 3.8 or newer. The CI matrix verifies Python 3.8, 3.11, and 3.13.

```bash
git clone https://github.com/Omnimemory/python-sdk.git
cd python-sdk
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

## Verification

Run the complete test suite before opening a change:

```bash
.venv/bin/python -m pytest -q
PYTHONPYCACHEPREFIX=/private/tmp/omem-pyc .venv/bin/python -m compileall -q omem tests
.venv/bin/python -m build
uvx twine check dist/*
```

For a package smoke test, install the generated wheel in a fresh virtual
environment and import `Memory` and `SearchResult`.

## Public API Policy

The public package surface is the set exported by `omem.__all__`. Keep new
behavior behind stable high-level APIs and preserve the existing ingest and
retrieval request contracts. Do not expose internal client helpers, transport
types, or backend-only routes without an explicit public API decision.

Write a focused regression test before changing behavior. Keep English and
Chinese documentation in sync whenever a public signature, return model, or
error contract changes.

## Documentation and Releases

- Update both README files for public SDK changes.
- Record user-visible changes in [CHANGELOG.md](CHANGELOG.md) and
  [CHANGELOG.zh.md](CHANGELOG.zh.md).
- Report security issues through [SECURITY.md](SECURITY.md), not public issues.
- Follow [RELEASE.md](RELEASE.md) for the release workflow.

## Pull Requests

Keep each pull request focused. Explain the public behavior change, include the
test command you ran, and call out compatibility implications.
