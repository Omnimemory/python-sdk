# MemAura 发布指南

`memaura` 仅通过仓库中的 GitHub Actions 工作流发布。工作流使用 PyPI Trusted
Publishing；不要为该项目创建、保存或提交 PyPI API token。

## 发布前检查

1. 在 [CHANGELOG.zh.md](CHANGELOG.zh.md) 中记录该版本面向用户的变更。
2. 确认目标版本尚未发布到 PyPI。
3. 将仓库配置为 PyPI Trusted Publisher，并保护 GitHub Actions 的 `pypi` environment。

## 发布流程

在 GitHub Actions 中手动运行 `Release MemAura to PyPI` 并输入目标版本。普通发布会校验 PEP 440 版本、运行测试、构建并检查构件、创建带注释的 tag、推送 tag，然后通过 OIDC 发布。

若 tag 已创建后发布失败，请使用相同版本并启用 `resume_publish` 再次运行该工作流。恢复模式会检出并验证既有 tag，只重试发布；不会修改 tag，也不会创建额外的发布提交。

发布后，在新的虚拟环境中从 PyPI 安装该版本，并从 `memaura` 导入 `Memory`。
