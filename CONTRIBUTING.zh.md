# 贡献指南

感谢你参与改进 OmniMemory Python SDK。

## 开发环境

请使用 Python 3.8 或更高版本。CI 会验证 Python 3.8、3.11 和 3.13。

```bash
git clone https://github.com/Omnimemory/python-sdk.git
cd python-sdk
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

## 验证

提交改动前请运行完整测试：

```bash
.venv/bin/python -m pytest -q
PYTHONPYCACHEPREFIX=/private/tmp/omem-pyc .venv/bin/python -m compileall -q omem tests
.venv/bin/python -m build
uvx twine check dist/*
```

建议在新的虚拟环境中安装生成的 wheel，并导入 `Memory` 与 `SearchResult` 做一次冒烟验证。

## 公开 API 约定

`omem.__all__` 是公开包接口的唯一边界。新增能力应通过稳定的高层 API 提供；除非经过明确的公开 API 决策，不要导出内部 client 辅助对象、传输类型或仅供后端使用的路由。

修改行为前先写聚焦的回归测试。只要公开方法签名、返回模型或错误契约发生变化，就同步更新中英文文档。

## 文档与发布

- 公开 SDK 改动需要同步更新两份 README。
- 用户可见的变更写入 [CHANGELOG.md](CHANGELOG.md) 和 [CHANGELOG.zh.md](CHANGELOG.zh.md)。
- 安全问题请按 [SECURITY.zh.md](SECURITY.zh.md) 提交，不要公开披露。
- 发布流程见 [RELEASE.zh.md](RELEASE.zh.md)。

## Pull Request

每个 Pull Request 请保持聚焦，说明公开行为变化、已运行的测试命令，以及兼容性影响。
