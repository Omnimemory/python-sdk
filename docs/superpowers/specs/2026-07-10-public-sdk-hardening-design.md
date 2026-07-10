# Public Python SDK Hardening Design

## Goal

Prepare `omem` for a major public release by exposing only supported OmniMemory
SaaS memory operations, making the documentation truthful, and ensuring every
release is tested before it is tagged and pushed.

## Scope

This design covers the Python package, its CI workflows, and public repository
documents. GitHub repository visibility, PyPI project ownership, and publishing
the release are intentionally out of scope; they require platform-side actions.

## Public API

`omem` version `2.0.0` will expose this stable high-level surface:

```python
from omem import (
    AddResult,
    Conversation,
    Memory,
    MemoryItem,
    SearchResult,
    OmemClientError,
    OmemHttpError,
    OmemAuthError,
    OmemForbiddenError,
    OmemRateLimitError,
    OmemQuotaExceededError,
    OmemPayloadTooLargeError,
    OmemValidationError,
    OmemServerError,
)
```

`Memory` accepts only `api_key`, `endpoint`, `device_no`, and `timeout_s`.
`endpoint` is an override for an OmniMemory-compatible gateway, such as a test
or private deployment using the same public data-plane contract. It is not a
promise of generic self-hosted core support.

Supported operations are:

- `add()` and `conversation().commit()` for asynchronous memory ingest;
- `add(..., wait=True)` for ingest-job polling;
- `search()` for legacy-compatible retrieval, including its `session_id` group
  filter and `fail_silent` handling;
- `search_hybrid()` and `device_no` for device-scoped hybrid retrieval.

`MemoryClient`, `SessionBuffer`, `CommitHandle`, `RetryConfig`, canonical wire
types, Graph/TKG models, Graph/TKG methods, debug configuration, and session
status methods are not part of the public package API. Unsupported methods and
their unreachable bodies are removed rather than left as runtime exceptions.
`MemoryItem` no longer exposes an `event_id`, because the public SDK has no
supported API that can use it.

Session-status removal includes every caller: `Memory.conversation()` no longer
accepts `sync_cursor`, `Conversation` has no cursor-sync state or helper, and
the low-level `MemoryClient.session()`, `SessionBuffer`, `get_session()`, and
`SessionStatusV1` are removed. Ingest-job polling remains available only through
the high-level `add(..., wait=True)` and `Conversation.commit(..., wait=True)`
flows.

## Data and Error Handling

The supported request payloads remain unchanged: API keys authenticate through
the existing gateway headers, `session_id` maps to the existing retrieval group
filter, and `device_no` routes hybrid retrieval. This work does not change any
router, core, or worker contract.

All HTTP and retry error classes remain public. The special
`OmemUnsupportedFeatureError` is removed along with the unsupported methods.
Callers continue to use `OmemClientError` as the common failure base class.

## Documentation

`README.md` and `README.zh.md` become equivalent descriptions of the stable
surface. They remove `user_id`, Graph/TKG, debug, and generic self-hosted
claims. The old internal SaaS architecture document is deleted from the public
repository.

The repository adds English and Chinese contribution, security, release, and
change-log documents. They explain supported Python versions, test commands,
how to report a vulnerability without posting secrets, and the `2.0.0` breaking
changes. No document contains credentials or platform-specific secrets.

## CI and Release Flow

A normal CI workflow runs on pull requests and pushes to `main` with Python
3.8, 3.11, and 3.13. The Python 3.13 classifier is added to `pyproject.toml`.
Each matrix entry runs the test suite. One build job also creates the wheel and
sdist, runs `twine check`, and installs the wheel in a fresh virtual environment
for an import smoke test.

The manual PyPI workflow receives a version input and an optional
`resume_publish` boolean. A normal release (`resume_publish=false`) performs
this order:

1. Normalize and validate the PEP 440 version, verify that `v<version>` does
   not already exist, and query PyPI to verify that `omem==<version>` has not
   already been published. Any non-404 PyPI response other than a successful
   absence check fails the release before a commit or tag is created.
2. Update the two version files in the temporary checkout, then install test
   and build tools, run the full test suite, build artifacts, run `twine check`,
   and perform the fresh-wheel import smoke test.
3. Commit the verified version change, create the version tag, and push both.
4. Publish the already verified artifacts through the configured PyPI trusted
   publisher or `PYPI_API_TOKEN` secret.

When a publish fails after the tag has been pushed, a maintainer reruns the
workflow with `resume_publish=true`. Resume mode checks out `v<version>`,
verifies that both version files equal the requested version, reruns the same
test/build/check/smoke verification, verifies that the version remains absent
from PyPI, and publishes without creating or pushing a commit or tag. A tag
that points to a different version is always rejected.

The release job uses a protected PyPI environment when configured. A failed
publish can be retried from the verified tag; no untested commit or tag is
pushed.

## Testing

Tests are written before each behavior change. They verify that:

- `Memory` rejects the removed `user_id` parameter;
- unsupported Graph/TKG, debug, and session APIs are absent from high-level and
  public exports;
- public `__all__` contains only the supported API;
- supported ingest, polling, legacy retrieval, hybrid retrieval, retry, and
  error mapping behavior remains intact;
- both README files describe the actual method signatures and omit removed
  features.

The existing mocked HTTP contract tests remain the primary test boundary. A
credentialed staging end-to-end test is not added to CI; it remains an explicit
release verification step outside this repository.

## Delivery Sequence

1. Remove unsupported code and models, reduce exports, update version, and add
   behavior tests; commit the API boundary as one change.
2. Align bilingual README and add public repository documents while removing
   the internal architecture document; commit documentation as one change.
3. Add normal CI and reorder the release workflow; commit release automation as
   one change.
4. Remove tracked Python bytecode; run the complete test/build/install checks,
   then commit this repository-hygiene change separately.

## Non-Goals

- Implementing Graph/TKG, debug, per-user isolation, or generic self-hosted
  core support.
- Changing any OmniMemory backend request or response contract.
- Making the GitHub repository public, claiming the PyPI project, or publishing
  `2.0.0`.
