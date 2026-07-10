# MemAura Python SDK

`memaura` is the Python SDK for MemAura. It lets an AI application store
conversations and retrieve the relevant memories later.

Languages: [English](README.md) | [中文](README.zh.md)

## Install

```bash
pip install memaura
```

## Before You Start

Create an API key in the MemAura dashboard. If your account uses a
bring-your-own-model policy, configure an LLM provider and model there before
writing memory.

## Quick Start

```python
from memaura import Memory

memory = Memory(api_key="qbk_xxx")

memory.add("conv-001", [
    {"role": "user", "content": "Caroline is visiting Seattle next week."},
    {"role": "assistant", "content": "I will remember that."},
])

# Processing is asynchronous. Use wait=True when the next step needs the result now.
result = memory.search("Where is Caroline going next week?")
for item in result:
    print(item.text)
```

## API

### `Memory`

```python
Memory(api_key, *, endpoint=None, device_no=None, timeout_s=30.0)
```

| Parameter | Description |
| --- | --- |
| `api_key` | Required MemAura API key. |
| `endpoint` | Optional MemAura-compatible gateway URL. The default is the cloud gateway. |
| `device_no` | Optional device identifier. When present, `search()` uses hybrid retrieval. |
| `timeout_s` | Per-request timeout in seconds. |

### `add(conversation_id, messages, *, wait=False, timeout_s=60.0)`

Stores a complete conversation. The default call returns immediately after the
ingest job is accepted. With `wait=True`, it returns an `AddResult` after the
job reaches a terminal state or the timeout expires.

```python
result = memory.add(
    "conv-002",
    [{"role": "user", "content": "I prefer morning meetings."}],
    wait=True,
)
if result and result.completed:
    print(result.job_id)
```

### `search(query, *, limit=10, session_id=None, fail_silent=False)`

Retrieves account-scoped memory. `session_id` narrows the search to the supplied
conversation group. With `fail_silent=True`, errors return an empty
`SearchResult` whose `error` field explains the failure.

```python
result = memory.search("What meeting time do I prefer?", session_id="conv-002")
print(result.to_prompt())
```

### `search_hybrid(query, *, device_no=None, limit=10, session_id=None, fail_silent=False)`

Runs device-scoped hybrid retrieval. Supply `device_no` here or when creating
`Memory`.

```python
result = memory.search_hybrid(
    "What did this device remember?",
    device_no="device-001",
)
```

### Conversation Buffer

Use a buffer when messages arrive one at a time.

```python
with memory.conversation("conv-003") as conversation:
    conversation.add({"role": "user", "content": "I enjoy coffee."})
    conversation.add({"role": "assistant", "content": "Noted."})
```

Leaving the context commits buffered messages. `conversation.commit(wait=True)`
waits for the corresponding ingest job.

## Result Models

| Model | Description |
| --- | --- |
| `MemoryItem` | One retrieved memory with text, score, timestamp, source, and entities. |
| `SearchResult` | Iterable result container with `items`, `latency_ms`, `error`, and `to_prompt()`. |
| `AddResult` | Ingest result with the conversation ID, message count, job ID, and completion flag. |

## Error Handling

```python
from memaura import MemAuraClientError, MemAuraRateLimitError

try:
    memory.search("recent preferences")
except MemAuraRateLimitError as exc:
    print(exc.retry_after_s)
except MemAuraClientError as exc:
    print(exc)
```

## Project Docs

- [Contributing](CONTRIBUTING.md) | [贡献指南](CONTRIBUTING.zh.md)
- [Security](SECURITY.md) | [安全政策](SECURITY.zh.md)
- [Changelog](CHANGELOG.md) | [更新日志](CHANGELOG.zh.md)
- [Release Guide](RELEASE.md) | [发布指南](RELEASE.zh.md)

## License

MIT
