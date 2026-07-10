# 发布指南

`omem` 通过仓库中的 GitHub Actions 发布。不要将 PyPI token 写入文件、提交记录或命令历史。

## 发布前检查

1. 确认当前版本的变更已记录在 [CHANGELOG.zh.md](CHANGELOG.zh.md)。
2. 运行完整测试、构建和 wheel 冒烟验证。
3. 确认目标版本尚未发布到 PyPI。
4. 在仓库设置中配置 PyPI Trusted Publisher，或配置受保护的 `PYPI_API_TOKEN` secret。

## 发布流程

在 GitHub Actions 手动运行 `Release Python SDK to PyPI`，输入目标版本。工作流会验证版本、测试并构建包，然后创建 tag 并发布。

若发布步骤失败但 tag 已成功创建，请以相同版本重新运行发布恢复模式。恢复模式会重新验证 tag 对应的代码和构建产物，不会重建 tag。

发布完成后，在新的虚拟环境中从 PyPI 安装该版本并导入 `Memory`。
