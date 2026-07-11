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

job = memory.add("conv-001", [
    {"role": "user", "content": "Caroline is visiting Seattle next week."},
    {"role": "assistant", "content": "I will remember that."},
])

awaited = memory.jobs.wait(job.job_id)

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
| `device_no` | Optional device identifier. When present, requests use the device-scoped memory namespace. |
| `timeout_s` | Per-request timeout in seconds. |

### `add(conversation_id, messages, *, commit_id=None, group_id=None, group_name=None, device_no=None, wait=False, timeout_s=60.0)`

Stores a complete conversation and always returns an `AddResult` acknowledgement
with the ingest `job_id`, `session_id`, `status`, and `status_url`. With
`wait=True`, `completed` is true only for successful terminal statuses such as
`succeeded` or `accumulated`.

Each message accepts `role`, `content`, optional `turn_id`, `timestamp`,
`name`, and `refer_list`. The Router-compatible aliases `id` / `uuid` and
`referList` are accepted too.

```python
result = memory.add(
    "conv-002",
    [{"role": "user", "content": "I prefer morning meetings."}],
    commit_id="conv-002:turn-1",
    wait=True,
)
if result and result.completed:
    print(result.job_id)
```

### `search(query, *, limit=10, group_id=None, session_id=None, fail_silent=False)`

Retrieves account-scoped memory. `group_id` narrows the search to the supplied
memory group; `session_id` remains a compatibility alias. With `fail_silent=True`, errors return an empty
`SearchResult` whose `error` field explains the failure.

`search()` always uses the regular retrieval endpoint. Use `search_hybrid()`
explicitly when hybrid retrieval is intended; this remains true even when a
default `device_no` is configured.

```python
result = memory.search("What meeting time do I prefer?", group_id="conv-002")
print(result.to_prompt())
```

### `search_hybrid(query, *, device_no=None, limit=10, group_id=None, session_id=None, fail_silent=False)`

Runs device-scoped hybrid retrieval. Supply `device_no` here or when creating
`Memory`.

```python
result = memory.search_hybrid(
    "What did this device remember?",
    device_no="device-001",
)
```

### `memory.jobs.get(job_id)` and `memory.jobs.wait(job_id, *, timeout_s=60.0, poll_interval_s=0.5)`

Reads or waits for an ingest job without submitting another write. Waiting stops
at both successful (`succeeded`, `accumulated`, `completed`) and unsuccessful
terminal statuses; inspect `status` to distinguish them.

```python
status = memory.jobs.get(job.job_id)
terminal = memory.jobs.wait(job.job_id, timeout_s=60)
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
| `MemoryItem` | Compatibility projection with text, score, timestamp, source, and entities. |
| `EvidenceDetail` | Normalized Router evidence with event, group, role, speaker, facts, and timestamp. |
| `SearchResult` | Iterable result container with `items`, `evidence_details`, latency, error, and `to_prompt()`. |
| `AddResult` | Ingest acknowledgement with conversation, job, session, status, and completion fields. |

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
