# omem

Python SDK for the omem memory service — give your AI agents long-term memory.

## Installation

```bash
pip install omem
```

## Prerequisites

Before using the SDK, you must configure an LLM provider in your dashboard:

1. Sign up at [omnimemory.ai](https://omnimemory.ai)
2. Go to **Dashboard → API Keys** and create a new API key (starts with `qbk_`)
3. Go to **Dashboard → Memory Policy** and add your LLM key:
   - Enter your LLM API key (e.g., OpenAI `sk-...`)
   - Select provider (OpenAI, DeepSeek, Qwen, etc.) and model
   - Set binding to "All API Keys"

> **Why?** Omni Memory uses LLMs to extract entities, events, and semantic knowledge from your conversations. Without an LLM configuration, you'll get a `Missing required data for core ingest` error.

## Quick Start

```python
from omem import Memory

mem = Memory(api_key="qbk_xxx")  # That's it!

# Save a multi-speaker conversation
mem.add("conv-001", [
    {"role": "user", "name": "Caroline", "content": "Hey Mel! Good to see you! How have you been?"},
    {"role": "user", "name": "Melanie", "content": "Hey Caroline! I'm swamped with the kids & work. What's up with you?"},
    {"role": "user", "name": "Caroline", "content": "I went to a LGBTQ support group yesterday and it was so powerful."},
    {"role": "user", "name": "Melanie", "content": "That's awesome! I'm so proud of you. How did it go?"},
    {"role": "user", "name": "Caroline", "content": "It was meaningful. I'm also going to a tech conference in Seattle next week."},
])

# Search memories (after backend processing ~5-30 seconds)
result = mem.search("What did Caroline do recently?")
if result:
    for item in result:
        print(f"[{item.score:.2f}] {item.text}")
```

## API Reference

### `Memory`

Main class for interacting with the memory service.

```python
# Minimal (just api_key) - SaaS mode (recommended)
mem = Memory(api_key="qbk_xxx")

# Multi-user apps (SaaS)
# NOTE: In SaaS, data is isolated at the **account** level.
# The optional user_id is accepted for future/backend-controlled
# isolation features but does not currently change data partitioning.
mem = Memory(api_key="qbk_xxx", user_id="user-123")

# Self-hosted deployment (advanced / not covered here)
mem = Memory(api_key="...", endpoint="https://my-instance.com/api/v1/memory")
```

**Parameters:**
| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `api_key` | ✅ Yes | - | Your API key. Get one at [omnimemory.ai](https://omnimemory.ai) |
| `user_id` | No | `None` | Optional end-user identifier (future/backend-controlled isolation in SaaS) |
| `endpoint` | No | Cloud service | Override for self-hosted deployments |
| `timeout_s` | No | `30.0` | Request timeout in seconds |

### `add(conversation_id, messages, *, wait=False, timeout_s=60.0)`

Save conversation messages to memory. Fire-and-forget by default; optionally wait for processing to finish.

```python
mem.add("conv-001", [
    {"role": "user", "content": "Book a meeting tomorrow at 3pm"},
    {"role": "assistant", "content": "Done! Meeting scheduled."},
])

# Wait for completion (immediate searchability)
result = mem.add("conv-002", [
    {"role": "user", "content": "Summarize yesterday's meeting"},
], wait=True, timeout_s=30.0)
if result and result.completed:
    mem.search("yesterday meeting")
```

**Parameters:**
- `conversation_id` — Unique identifier for the conversation
- `messages` — List of messages with:
  - `role` — "user" for human speakers, "assistant" for AI responses
  - `content` — The message text
  - `name` — (Optional) Speaker name for multi-party conversations
- `wait` — If True, block until backend processing completes (default False)
- `timeout_s` — Timeout when `wait=True` (default 60s)

**Note:** Call once per conversation (not per message) for best results. Fire-and-forget mode becomes searchable after backend processing (~5-30 seconds). With `wait=True`, `add` returns an `AddResult` containing `job_id` and `completed` status.

### `search(query, *, limit=10, fail_silent=False)`

Search memories. Returns strongly-typed results.

```python
result = mem.search("meeting with Caroline")
if result:
    for item in result:
        print(f"[{item.score:.2f}] {item.text}")
```

**Parameters:**
- `query` — Search question
- `limit` — Maximum results (default: 10)
- `fail_silent` — Return empty result on error instead of raising (default: False)

**Returns:** `SearchResult` with:
- Truthy check: `if result: ...`
- Iteration: `for item in result: ...`
- LLM formatting: `result.to_prompt()`

## Models

The SDK provides strongly-typed return models:

| Model | Description |
|-------|-------------|
| `SearchResult` | Search results container with `items`, `latency_ms`, iteration support |
| `MemoryItem` | Single search result with `text`, `score`, `timestamp`, `event_id` |
| `EventContext` | Full TKG context: `entities`, `knowledge`, `places`, `utterances` |
| `ExtractedKnowledge` | Structured fact with `summary`, `importance`, `timestamp` |
| `Evidence` | Source utterance with `text`, `confidence`, `timestamp` |
| `Entity` | TKG entity with `id`, `name`, `type`, `aliases` |
| `Event` | TKG event with `id`, `summary`, `timestamp` |
| `AddResult` | Ingestion result with `job_id`, `completed` status |

## Error Handling

```python
from omem import OmemClientError, OmemRateLimitError

try:
    result = mem.search("query")
except OmemRateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after_s}s")
except OmemClientError as e:
    print(f"Error: {e}")
```

For agent robustness, use `fail_silent=True`:

```python
# Never raises — returns empty SearchResult on error
result = mem.search("query", fail_silent=True)
```

## Multi-User Apps (SaaS)

In SaaS, **data is isolated at the account level**. The backend (Gateway + BFF)
owns the effective `user_tokens` and `client_meta` based on your account
configuration, not on SDK-side settings.

You can still tag calls with an end-user identifier for your own tracking:

```python
mem = Memory(api_key="qbk_xxx", user_id="alice")  # for your app's bookkeeping

mem.add("conv-1", [{"role": "user", "content": "I love coffee"}])
result = mem.search("what do I like?")
```

Today, using different `user_id` values in SaaS **does not** guarantee separate
vector spaces; per-user isolation is a potential future feature controlled via
backend `memory_policy`, not SDK-side `user_tokens`.

For strict isolation in SaaS **today**, use separate accounts / API keys.

## TKG Features: Knowledge & Evidence

The SDK exposes the Temporal Knowledge Graph (TKG) for advanced use cases.

### `explain_event(item)` — Full TKG Context

Get everything the TKG extracted from a search result:

```python
result = mem.search("Caroline support group", limit=1)
item = result.items[0]

ctx = mem.explain_event(item)
if ctx:
    # Entities mentioned
    print(f"Entities: {ctx.entities}")  # ['Caroline (PERSON)']
    
    # Extracted facts (the real value!)
    for k in ctx.knowledge:
        print(f"Fact: {k.summary}")  # "Caroline went to support group on 2026-01-14"
        print(f"  Importance: {k.importance}")
    
    # Source utterances
    print(f"Sources: {ctx.utterances}")
```

### `get_entity_history(entity)` — All Evidence for an Entity

Get all utterances/evidence related to an entity:

```python
history = mem.get_entity_history("Caroline", limit=10)
for e in history:
    print(f"[{e.confidence:.2f}] {e.text}")
    print(f"  Timestamp: {e.timestamp}")
```

### `get_evidence_for(item)` — Source for a Search Result

Trace a search result back to its source utterance:

```python
result = mem.search("tech conference", limit=1)
item = result.items[0]

evidence = mem.get_evidence_for(item)
for e in evidence:
    print(f"Source: {e.text}")
```

### `resolve_entity(name)` — Entity Resolution

Resolve an entity name to its TKG ID:

```python
entity = mem.resolve_entity("Caroline")
if entity:
    print(f"ID: {entity.id}")
    print(f"Type: {entity.type}")  # PERSON
    print(f"Aliases: {entity.aliases}")
```

## Advanced: Conversation Buffer

For fine-grained control over when to commit:

```python
with mem.conversation("conv-001") as conv:
    conv.add({"role": "user", "content": "First message"})
    conv.add({"role": "assistant", "content": "Reply"})
    # Auto-commits on exit
```

Or manually:

```python
conv = mem.conversation("conv-001")
conv.add({"role": "user", "content": "Hello"})
result = conv.commit()  # Returns AddResult with job_id
```

## Future: Self-Hosted User Isolation (Design Sketch)

> Status: Design only – not implemented in the public SaaS service.

For self-hosted deployments that need per-end-user isolation within a tenant, a
cleaner design than `user_tokens` is:

### Recommended: `X-User-ID` Header

In this model:

- The deployment API key authenticates the tenant
- `X-User-ID` identifies the end user within that tenant
- The server enforces isolation based on `(tenant_id, user_id)`

Example future shape (not yet wired end-to-end):

```python
client = MemoryClient(
    base_url="http://localhost:8000/api/v1/memory",
    api_key="deployment_key",
    # user_id would eventually map to X-User-ID header on requests
    # user_id="alice",
)
```

### Alternative: Scoped API Keys

Another option for self-hosted tenants is to issue per-user API keys that
encode both tenant and user scope:

```python
client = MemoryClient(
    base_url="http://localhost:8000/api/v1/memory",
    api_key="qbk_tenant_alice_scoped_key",
)
```

In this model, the server derives both `tenant_id` and `user_id` from the key
itself and does not need a separate header.

These patterns are documented here as forward-looking guidance only; the SaaS
service uses account-level isolation based solely on the API key.

## License

MIT
