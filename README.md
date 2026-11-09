<h1 align="center">Codex Project Rescue</h1>

<p align="center"><strong>先查看恢复证据，再找回丢失的本地项目列表与聊天归属。</strong></p>

<p align="center"><a href="#快速开始">开始使用</a> · <a href="#如何使用">恢复步骤</a> · <a href="docs/recovery-model.md">恢复原理</a> · <a href="#支持范围与限制">支持范围</a></p>

<p align="center"><img src="docs/badges/stage.svg" alt="Stage: Alpha"> <img src="docs/badges/runtime.svg" alt="Runtime: Python 3.11+"> <img src="docs/badges/platform.svg" alt="Platform: Windows"></p>

## 解决什么问题

独立社区工具，不是 OpenAI 官方修复程序。当前为 `0.1.0a1` 预览版。扫描不修改 Codex；应用修复需由你手动退出 Codex。不能保证所有丢失数据都能恢复，也不保证升级或未来新账号会自动同步。

本地文件夹和旧聊天仍在，Codex 左侧却显示“没有项目”。项目目录、数据库记录、账号侧栏状态是不同的数据层；仅重新添加文件夹，可能建立一个没有旧聊天的新项目入口。

这个工具从已有状态与数据库中确认原项目身份，生成可审阅的恢复预览。它不会新建项目 ID，也不会按聊天目录猜测归属。

如果当前项目状态已经完整，窗口却仍为空，工具会提示排查界面加载问题，而不是反复写入配置。社区在 macOS 上报告过“文件 → 新建窗口”的免退出绕行方法；Windows 尚未在本项目验证。[案例与证据边界](docs/recovery-model.md)

## 使用示例

![恢复预览：当前账号缺少一个项目，另一个已保存账号保留原记录](docs/preview.png)

上图是实际运行的工具界面，使用独立的合成数据目录：

```text
找到 1 个可明确识别的普通本地项目。
当前账号：现有项目 0 → 恢复后项目 1；新增聊天归属 1
已保存账号：现有项目 1 → 恢复后项目 1；新增聊天归属 0
```

这是合成数据示例，不是实际用户的恢复数量。预览、写入成功、界面恢复是三个不同状态；写入后仍需打开 Codex 检查原项目和旧聊天。

## 快速开始

### Windows 图形界面

当前源码需要 **Python 3.11 或更高版本，包含 tkinter**，运行时仅用 Python 标准库。版本与入口定义见 [pyproject.toml](pyproject.toml)。

1. 下载本仓库 ZIP 并解压，或克隆仓库。
2. 双击 `start-windows.cmd`，或在解压目录运行：

   ```powershell
   python launch.py
   ```

3. 点击“扫描并预览”。此时可以保持 Codex 打开。

GitHub Actions 的 `Checks` 工作流会在测试通过后构建 `CodexProjectRescue-Windows-preview` 制品，其中包含便携 ZIP 和校验值；它不是稳定 Release。解压 ZIP 后双击 `CodexProjectRescue.exe`，无需安装 Python。下载制品需要登录 GitHub，制品可能过期。首次预览版暂不提供自动更新或下载执行远程脚本的入口。

### 命令行

```powershell
python -m pip install -e .
codex-project-rescue scan
codex-project-rescue --scope all scan
codex-project-rescue scan --json
```

`--home` 可指定 Codex 数据目录；默认使用 `CODEX_HOME`，否则使用用户目录下的 `.codex`。工具不会读取登录凭据文件。

## 如何使用

1. **扫描。** 识别保存的项目、数据库身份映射、可访问根目录及明确的聊天归属。可以选取一份历史 global-state JSON 作为额外证据。
2. **查看预览。** 点击“查看项目明细”检查名称、目录和恢复依据。默认仅恢复当前账号。只有这些账号都由你管理并需要共享本地项目列表时，才勾选“所有已保存账号”。冲突、云端关联和证据不足的记录会跳过。
3. **由你手动退出 Codex。** 保持恢复工具打开，或从资源管理器重新运行它。不要从 Codex 内置终端启动后依赖它在 Codex 退出时继续运行。
4. **备份并修复。** 工具检查应用已退出、版本受支持、预览没有过期，先备份，再合并五类项目字段。如状态变化，重新扫描并审阅预览。
5. **手动打开 Codex 核验。** 查看原项目、几条旧聊天，以及希望使用的其他账号。工具不会自动启动或关闭 Codex。

备份默认保存在 `%LOCALAPPDATA%\CodexProjectRescue\backups`，不在 Codex 数据目录内。可以更改位置。备份包含私有账号状态及本地数据库，请保留在自己的电脑。

撤销：手动退出 Codex，在工具中选择“撤销上次修复”，选中一次备份目录。只撤销此次修改的项目字段，保留其他新设置；如果项目字段已有后续变化，会拒绝覆盖。[备份与撤销细节](docs/recovery-model.md#备份与撤销)

## 支持范围与限制

| 项目 | 当前行为 |
| --- | --- |
| 实际写入平台 | Windows |
| 已核对写入版本 | Microsoft Store `OpenAI.Codex 26.1103.4239.0` |
| 其他版本 | 能识别状态格式时允许只读扫描，拒绝写入 |
| 项目来源 | 当前/已保存账号状态、可选历史 JSON、现有 `state_5.sqlite` |
| 多账号 | 按执行时保存的账号动态处理；修复后首次登录的新账号需重新同步 |
| 云端关联项目 | 本版不迁移、不解除关联，保留已有记录 |
| 缺失或冲突 | 跳过并报告，不创建替代项目，不推测聊天归属 |
| 会话文件 | 检查文件存在，包括 `.jsonl.zst`；不证明正文完整或可以正常打开 |
| 不适用 | 恢复已删除文件、已删除会话正文、跨 Windows 用户迁移、云端项目找回 |

**只有本地目录存在，并不足以承诺聊天归属恢复。** 项目列表、身份映射、线程索引或会话文件缺失时，需要分别判断。

## 隐私与安全

工具没有遥测、网络请求、后台服务、计划任务或自动账号切换。它不修改 SQLite、会话正文、项目源码、登录信息、迁移标记或文件访问授权。两个 JSON 文件分别替换，不能作为一个跨文件原子事务；中途断电时应保留备份并检查状态。

匿名诊断可以分享，完整备份包含私人数据。请勿将备份和真实聊天上传到公开 Issue。[安全说明](SECURITY.md)

## 开发与验证

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src launch.py
python -m pip install pyinstaller==6.16.0
python -m PyInstaller --noconfirm --clean --onefile --windowed --name CodexProjectRescue --paths src launch.py
python scripts/package_windows.py
```

测试使用临时合成账号、项目和数据库，覆盖多账号变化、原 ID 保留、冲突保护、过期预览、写入失败回滚、撤销与匿名报告。它们不等于在每个 Codex 版本或每台电脑上验证成功。

发布包使用独立 Windows CPython 3.13 环境构建，携带运行库许可和 SHA-256 校验值。打包脚本拒绝 Conda 环境，以避免将本机其他软件的动态库混入分发文件。[第三方说明](THIRD_PARTY_NOTICES.md)

不建议直接扩展版本白名单：先核实对应版本的项目状态格式、账号切换行为及合成数据测试，再记录适配证据。欢迎贡献匿名诊断和最小复现。[贡献指南](CONTRIBUTING.md) · [隐私与安全](SECURITY.md)

## 来源与许可

恢复思路参考 GitHub 社区已报告成功的案例：[原 ID 与侧栏记录恢复 #54538](https://github.com/openai/codex/issues/54538)、[账号切换与窗口加载问题 #59895](https://github.com/openai/codex/issues/59895)。本工具代码独立编写，不直接复制他人案例脚本，不把社区报告当成官方兼容承诺。

许可证尚待仓库所有者确定；公开发布前将明确授权范围。本项目不使用 OpenAI 标志，不隶属于 OpenAI。
