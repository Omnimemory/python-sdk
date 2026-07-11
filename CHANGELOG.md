# Changelog

All notable user-visible changes are documented here.

## 1.0.0 - Unreleased

### Added

- MemAura Python SDK for conversation ingest, asynchronous job waiting, and
  account-scoped memory retrieval.
- Device-scoped hybrid retrieval through `search_hybrid()`.
- Optional `session_id` filtering for both retrieval methods.
- Supported Python runtimes 3.8 through 3.13.
- Explicit regular versus hybrid retrieval, job acknowledgements, job waiting,
  caller-controlled ingest idempotency, and normalized retrieval evidence.

### Security

- Release artifacts are verified in CI before publication through PyPI Trusted
  Publishing.
