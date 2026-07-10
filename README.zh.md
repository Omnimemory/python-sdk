# omem

`omem` 是 OmniMemory 的 Python SDK，用于让 AI 应用写入对话记忆，并在需要时检索相关内容。

语言: [English](README.md) | [中文](README.zh.md)

## 安装

```bash
pip install omem
```

## 使用前准备

在 OmniMemory 控制台创建 API Key。若账户使用自带模型策略，请先在控制台配置 LLM provider 和 model，再写入记忆。

## 快速开始

```python
from omem import Memory

memory = Memory(api_key="qbk_xxx")

memory.add("conv-001", [
    {"role": "user", "content": "Caroline 下周要去西雅图。"},
    {"role": "assistant", "content": "我会记住这件事。"},
])

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
| `api_key` | 必填，OmniMemory API Key。 |
| `endpoint` | 可选，兼容 OmniMemory 数据面契约的 gateway 地址；默认使用云端 gateway。 |
| `device_no` | 可选设备标识。设置后，`search()` 自动使用混合检索。 |
| `timeout_s` | 单次请求超时时间，单位为秒。 |

### `add(conversation_id, messages, *, wait=False, timeout_s=60.0)`

写入一段完整对话。默认在 ingest job 被接受后立即返回；传入 `wait=True` 时，SDK 会等待 job 到达终态或超时，并返回 `AddResult`。

```python
result = memory.add(
    "conv-002",
    [{"role": "user", "content": "我更喜欢上午开会。"}],
    wait=True,
)
if result and result.completed:
    print(result.job_id)
```

### `search(query, *, limit=10, session_id=None, fail_silent=False)`

检索账号范围内的记忆。`session_id` 用于将查询限定在指定对话组；当 `fail_silent=True` 时，请求失败会返回空的 `SearchResult`，错误信息位于 `error` 字段。

```python
result = memory.search("我喜欢什么会议时间？", session_id="conv-002")
print(result.to_prompt())
```

### `search_hybrid(query, *, device_no=None, limit=10, session_id=None, fail_silent=False)`

执行设备级混合检索。可在本次调用中传入 `device_no`，也可在创建 `Memory` 时设置。

```python
result = memory.search_hybrid(
    "这个设备记住了什么？",
    device_no="device-001",
)
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
| `MemoryItem` | 单条召回记忆，包含文本、分数、时间、来源和实体。 |
| `SearchResult` | 可迭代结果容器，包含 `items`、`latency_ms`、`error` 和 `to_prompt()`。 |
| `AddResult` | 写入结果，包含对话 ID、消息数、job ID 和完成状态。 |

## 错误处理

```python
from omem import OmemClientError, OmemRateLimitError

try:
    memory.search("最近的偏好")
except OmemRateLimitError as exc:
    print(exc.retry_after_s)
except OmemClientError as exc:
    print(exc)
```

## 项目文档

- [贡献指南](CONTRIBUTING.zh.md) | [Contributing](CONTRIBUTING.md)
- [安全政策](SECURITY.zh.md) | [Security](SECURITY.md)
- [更新日志](CHANGELOG.zh.md) | [Changelog](CHANGELOG.md)
- [发布指南](RELEASE.zh.md) | [Release Guide](RELEASE.md)

## 许可证

MIT
