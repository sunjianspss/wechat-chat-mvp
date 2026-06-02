# AGENTS.md - WeChat Chat Analyzer MVP

本文件给 coding agent 使用。任何 agent 接到本项目任务后，必须先读本文件，再开始修改代码。

## 项目定位

本项目是一个本地 WeChat 群聊分析 MVP：

```text
微信窗口 -> 自动截图/向上滚动 -> OCR -> 去重清洗 -> summary.md
```

核心目标：

- 只处理用户本机可见的微信聊天窗口。
- 不解密微信数据库。
- 不提取密钥、cookie、token 或系统凭证。
- 不上传聊天记录、截图、OCR 文本或摘要。
- 输出保存在本地 `runs/YYYYMMDD-HHMMSS/`。

## 项目结构

| 路径 | 说明 |
| --- | --- |
| `wechat_analyzer.py` | 主流程：截图、OCR、清洗、总结、清理 |
| `run_wechat.sh` | 常用运行入口 |
| `helpers/ocr_vision.swift` | macOS Vision OCR 辅助程序 |
| `helpers/mac_control.swift` | macOS 窗口控制和滚动辅助程序 |
| `.bin/` | 编译后的本地 helper，忽略提交 |
| `runs/` | 采集结果，包含隐私数据，忽略提交 |

## 隐私和安全规则

- 不读取、总结、复制、上传或外传 `runs/` 下的聊天内容，除非任务明确要求做本地结果检查。
- 不把 `runs/`、截图、`ocr_raw.json`、`ocr_raw.txt`、`chat_clean.md`、`summary.md` 纳入提交或 PR。
- 不修改系统 Python，不建议卸载或覆盖 macOS 自带 Python。
- Python 命令必须使用 `uv run --python 3.12`。
- 涉及 macOS 权限、屏幕录制、辅助功能、微信窗口控制的变更，需要在 PR 中明确风险。
- 不自动打开、点击或操作微信，除非任务明确要求测试采集流程。

## 常用命令

检查环境：

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --python 3.12 python wechat_analyzer.py doctor
```

查看命令帮助：

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --python 3.12 python wechat_analyzer.py --help
```

采集聊天：

```bash
./run_wechat.sh --screens 60 --quality precise
```

处理已有截图：

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --python 3.12 python wechat_analyzer.py ocr /path/to/screenshots
UV_CACHE_DIR=/private/tmp/uv-cache uv run --python 3.12 python wechat_analyzer.py summarize /path/to/screenshots
```

清理历史输出：

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --python 3.12 python wechat_analyzer.py cleanup --runs-dir runs --older-than-days 14 --keep-latest 10
```

## Agent 工作流

本项目已接入 AI agent 工作流：

| 文件 | 说明 |
| --- | --- |
| `config/agent-routing.yml` | 标签到 agent 的路由规则 |
| `scripts/validate-agent-task.sh` | GitHub Issue 校验 |
| `scripts/route-agent-task.sh` | GitHub Issue 路由 |
| `scripts/run-agent-task.sh` | Git worktree 模式运行 agent |
| `scripts/run-local-agent-task.sh` | 非 GitHub / 非 git 仓库的本地任务模式 |
| `docs/state-machine.md` | Issue / PR / CI 状态机 |
| `docs/architecture.md` | 工作流架构图 |

当前目录如果还不是 git 仓库，先使用本地任务模式：

```bash
scripts/run-local-agent-task.sh docs/sample-local-agent-task.md
```

如果以后接入 GitHub 仓库，再使用：

```bash
scripts/validate-agent-task.sh 123
scripts/route-agent-task.sh 123
scripts/run-agent-task.sh 123
```

## 开发规则

- 优先保持单文件 MVP 的简洁性，除非任务明确要求拆模块。
- 新增功能要保留现有 CLI 参数兼容性。
- 对 OCR、去重、摘要逻辑的修改，要说明可能影响历史输出格式。
- 对截图和滚动逻辑的修改，要说明是否需要 Accessibility / Screen Recording 权限。
- 不做与任务无关的重构。
- 修改完成后至少运行 `--help`，能安全运行时再运行 `doctor` 或更具体的命令。

## 完成标准

任务完成必须说明：

- 改了什么。
- 是否影响隐私边界。
- 运行了哪些命令。
- 是否触碰 `runs/` 数据。
- 是否需要用户手动授权或操作微信窗口。
