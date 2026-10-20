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

## V4 Card/Episode API

`MemoryV4` 是面向当前 `/api/v3` 数据面的新增客户端；原有 `Memory` 类继续服务已有的
`/api/v2` 接入，不会因本次升级改变语义。

```python
from memaura import MemoryV4

memory = MemoryV4(api_key="qbk_xxx", device_no="DEVICE-001")
ack = memory.ingest([
    {"role": "user", "content": "我偏好周三下午进行产品评审。"},
    {"role": "assistant", "content": "好的，已记下。"},
])
job = memory.jobs.wait(ack.job_id, timeout_s=300)
if job.status == "failed":
    raise RuntimeError(job.error)

result = memory.retrieve("我偏好什么时候进行产品评审？", top_k=5)
for card in result.cards:
    print(card.content)
```

### `MemoryV4`

```python
MemoryV4(api_key, *, endpoint=None, device_no=None, timeout_s=30.0)
```

`endpoint` 默认为 `https://api.omnimemory.cn/api/v3`。`device_no` 设置默认
`X-Device-No` 请求头，单次操作可覆盖。`MemoryV4` 支持上下文管理器，也提供 `close()`。

### `ingest(turns, *, language="auto", timezone=None, device_no=None, wait_for="staged", wait_timeout_seconds=120.0)`

调用 `POST /memory/ingest_4` 并返回 `V4Job`。`turns` 不能为空；每条 turn 必须包含
`content`，还可包含 `role`、`turn_id`、`timestamp`、`sender_name` 和 `refer_list`。
`language` 可取 `auto`、`zh` 或 `en`；`wait_for` 可取 `staged` 或 `searchable`；
`wait_timeout_seconds` 必须在 `(0, 300]` 范围内。

### `retrieve(query, **filters)`

调用 `POST /memory/retrieval_4` 并返回 `V4RetrievalResult`。

| 参数 | 类型/默认值 | 说明 |
| --- | --- | --- |
| `query` | 必填 `str` | 非空检索问题。 |
| `top_k` | 可选 `int` | 1–100 的结果数量。 |
| `vector_weight` | `float = 0.8` | 0–1 的向量/文本融合权重。 |
| `tag_keys` | sequence | 硬标签过滤。 |
| `role` | 可选 `str` | Card 角色过滤。 |
| `scope_type` | `account`、`api_key` 或 `device` | 记忆作用域。 |
| `start_time`, `end_time` | 可选 `str` | 显式时间范围。 |
| `entity_id` | 可选 `str` | 实体过滤。 |
| `entity_match_mode` | `primary`、`involved` 或 `source` | 实体匹配方式。 |
| `participant_roles` | sequence | 参与角色过滤。 |
| `device_no` | 可选 `str` | 单次操作设备号覆盖。 |
| `include_query_analysis` | `bool = False` | 返回查询分析。 |
| `include_details` | `bool = False` | 在 `details` 中保留完整响应。 |

### `memory.jobs.get(job_id)` 与 `memory.jobs.wait(job_id, *, timeout_s=300.0, poll_interval_s=1.0)`

`get()` 调用 `GET /memory/ingest_4/jobs/{job_id}`；`wait()` 只轮询该任务。
等待状态为 `queued`、`staged`、`processing`、`buffered` 和 `indexing`，终态为
`succeeded` 与 `failed`。本地超时时抛出 `V4JobTimeoutError`，其中的 `job_id` 和
`last_job` 可用于继续查询。

### V4 返回模型

| 模型 | 字段 |
| --- | --- |
| `V4Job` | `job_id`、可选 `status`、`wait_timed_out`、可选 `error` |
| `V4Episode` | `episode_id`、`summary` |
| `V4Card` | `card_id`、`role`、`content`、`episodes` |
| `V4RetrievalResult` | `cards`、可选 `query_analysis`、可选 `details`；支持 `bool()` 与 `len()` |

V4 写入不会自动重试。提交失败且尚未取得 `job_id` 时，应先排查实际结果，再决定是否重新提交。
本地等待超时不会取消后台任务，请继续查询同一个 `job_id`。检索支持 `top_k`、向量/文本融合权重、
硬标签、角色和作用域、显式时间范围，以及实体和参与角色过滤。

## 旧版 V2 API

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

当消息逐条到达时，可以使用 `Conversation` 对话缓冲区。

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

`Memory` 与 `MemoryV4` 都支持 `with`，并提供 `close()` 释放 HTTP 客户端。

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

公开错误层级包括 `MemAuraClientError`、`MemAuraHttpError`、
`MemAuraAuthError`、`MemAuraForbiddenError`、`MemAuraRateLimitError`、
`MemAuraQuotaExceededError`、`MemAuraPayloadTooLargeError`、
`MemAuraValidationError` 和 `MemAuraServerError`。HTTP 错误提供 `status_code`、
`error`、`request_id` 与 `retry_after_s`。本地参数错误也可能抛出 `ValueError`；
V4 任务等待超时会抛出 `V4JobTimeoutError`。

## 测试覆盖率

CI 要求全部手写 `memaura` 包同时达到 100% 语句覆盖率和分支覆盖率。本地可运行同一门禁：

```bash
python -m pytest --cov=memaura --cov-branch --cov-fail-under=100
```

本 Python 仓库没有将生成产物纳入覆盖率口径。

## 项目文档

- [贡献指南](CONTRIBUTING.zh.md) | [Contributing](CONTRIBUTING.md)
- [安全政策](SECURITY.zh.md) | [Security](SECURITY.md)
- [更新日志](CHANGELOG.zh.md) | [Changelog](CHANGELOG.md)
- [发布指南](RELEASE.zh.md) | [Release Guide](RELEASE.md)

## 许可证

MIT
