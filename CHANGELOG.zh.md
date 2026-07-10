# 更新日志

这里记录所有面向用户的重要变更。

## 1.0.0 - 未发布

### 新增

- MemAura Python SDK，支持对话写入、异步 job 等待和账号范围记忆检索。
- 通过 `search_hybrid()` 提供设备级混合检索。
- 两种检索方法均支持可选的 `session_id` 过滤。
- 支持 Python 3.8、3.11 和 3.13。

### 安全

- 发布前在 CI 中验证构件，并通过 PyPI Trusted Publishing 发布。
