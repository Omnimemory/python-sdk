# Changelog

All notable user-visible changes are documented here.

## 2.0.0 - Unreleased

### Changed

- The public SDK now focuses on conversation ingest, job waiting, legacy
  retrieval, and device-scoped hybrid retrieval.
- `search()` and `search_hybrid()` support an optional `session_id` group filter.
- Python 3.13 is part of the supported runtime matrix.

### Removed

- The unused `user_id`, public inspection helpers, session status, and cursor
  synchronization surfaces.
- Graph/TKG models and methods, backend configuration helpers, and raw
  inspection fields that had no supported public route.
- Top-level exports for internal transport clients and wire types.
