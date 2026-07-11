# MemAura Python SDK

`memaura` 是 MemAura 的 Python SDK，用于让 AI 应用写入对话记忆，并在需要时检索相关内容。

语言: [English](README.md) | [中文](README.zh.md)

## 安装

```bash
pip install memaura
```

## 使用前准备

在 MemAura 控制台创建 API Key。若账户使用自带模型策略，请先在控制台配置 LLM provider 和 model，再写入记忆。

## 快速开始

```python
from memaura import Memory

memory = Memory(api_key="qbk_xxx")

job = memory.add("conv-001", [
    {"role": "user", "content": "Caroline 下周要去西雅图。"},
    {"role": "assistant", "content": "我会记住这件事。"},
])

terminal = memory.jobs.wait(job.job_id)

# 后端异步处理完成后即可检索；需要立即使用时请传 wait=True。
result = memory.search("Caroline 下周去哪里？")
for item in result:
    print(item.text)
```

## API

### `Memory`

```python
Memory(api_key, *, endpoint=None, device_no=None, timeout_s=30.0)
```

| 参数 | 说明 |
| --- | --- |
| `api_key` | 必填，MemAura API Key。 |
| `endpoint` | 可选，兼容 MemAura 数据面契约的 gateway 地址；默认使用云端 gateway。 |
| `device_no` | 可选设备标识。设置后，请求使用该设备隔离的记忆命名空间。 |
| `timeout_s` | 单次请求超时时间，单位为秒。 |

### `add(conversation_id, messages, *, commit_id=None, group_id=None, group_name=None, device_no=None, wait=False, timeout_s=60.0)`

写入一段完整对话，并始终返回包含 `job_id`、`session_id`、`status`、`status_url` 的 `AddResult` ack。传入 `wait=True` 时，任务进入 `succeeded` 或 `accumulated` 等成功终态后，`completed` 才会为真。

每条消息支持 `role`、`content`、可选的 `turn_id`、`timestamp`、`name` 和 `refer_list`；同时兼容 Router 的 `id` / `uuid` 与 `referList` 别名。

```python
result = memory.add(
    "conv-002",
    [{"role": "user", "content": "我更喜欢上午开会。"}],
    commit_id="conv-002:turn-1",
    wait=True,
)
if result and result.completed:
    print(result.job_id)
```

### `search(query, *, limit=10, group_id=None, session_id=None, fail_silent=False)`

检索账号范围内的记忆。`group_id` 用于将查询限定在指定记忆组，`session_id` 保留为兼容别名；当 `fail_silent=True` 时，请求失败会返回空的 `SearchResult`，错误信息位于 `error` 字段。

`search()` 始终调用普通检索；需要混合检索时必须显式调用 `search_hybrid()`，即使构造 `Memory` 时已设置默认 `device_no` 也是如此。

```python
result = memory.search("我喜欢什么会议时间？", group_id="conv-002")
print(result.to_prompt())
```

### `search_hybrid(query, *, device_no=None, limit=10, group_id=None, session_id=None, fail_silent=False)`

执行设备级混合检索。可在本次调用中传入 `device_no`，也可在创建 `Memory` 时设置。

```python
result = memory.search_hybrid(
    "这个设备记住了什么？",
    device_no="device-001",
)
```

### `memory.jobs.get(job_id)` 与 `memory.jobs.wait(job_id, *, timeout_s=60.0, poll_interval_s=0.5)`

读取或等待一个 ingest 任务，不会重新提交写入。等待在成功终态（如 `succeeded`、`accumulated`、`completed`）和失败终态都会停止；请检查 `status` 区分结果。

```python
status = memory.jobs.get(job.job_id)
terminal = memory.jobs.wait(job.job_id, timeout_s=60)
```

### 对话缓冲区

当消息逐条到达时，可以使用对话缓冲区。

```python
with memory.conversation("conv-003") as conversation:
    conversation.add({"role": "user", "content": "我喜欢咖啡。"})
    conversation.add({"role": "assistant", "content": "记住了。"})
```

退出上下文时会自动提交缓冲中的消息。`conversation.commit(wait=True)` 可等待对应的 ingest job。

## 返回模型

| 模型 | 说明 |
| --- | --- |
| `MemoryItem` | 兼容投影，包含文本、分数、时间、来源和实体。 |
| `EvidenceDetail` | Router 归一化证据，包含事件、分组、角色、发言者、事实和时间。 |
| `SearchResult` | 可迭代结果容器，包含 `items`、`evidence_details`、延迟、错误和 `to_prompt()`。 |
| `AddResult` | 写入 ack，包含对话、job、session、状态和完成字段。 |

## 错误处理

```python
from memaura import MemAuraClientError, MemAuraRateLimitError

try:
    memory.search("最近的偏好")
except MemAuraRateLimitError as exc:
    print(exc.retry_after_s)
except MemAuraClientError as exc:
    print(exc)
```

## 项目文档

- [贡献指南](CONTRIBUTING.zh.md) | [Contributing](CONTRIBUTING.md)
- [安全政策](SECURITY.zh.md) | [Security](SECURITY.md)
- [更新日志](CHANGELOG.zh.md) | [Changelog](CHANGELOG.md)
- [发布指南](RELEASE.zh.md) | [Release Guide](RELEASE.md)

## 许可证

MIT
