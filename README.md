# WeChat Chat Analyzer MVP

把微信里可见的聊天内容整理成文本和摘要：

```text
微信窗口 -> 自动截图/向上滚动 -> OCR -> 去重清洗 -> summary.md
```

不解密数据库，不提取密钥，不上传聊天记录。

## 使用

先打开微信目标聊天窗口，关闭图片预览、视频预览等浮层，然后运行：

```bash
cd /Users/sun/Documents/Mac-pro/wechat-chat-mvp
UV_CACHE_DIR=/private/tmp/uv-cache uv run --python 3.12 python wechat_analyzer.py doctor
./run_wechat.sh --screens 80 --quality precise --scroll-amount 3
```

第一次使用先开权限：

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --python 3.12 python wechat_analyzer.py permissions --open
```

在 macOS 设置里开启当前终端的：

- `Privacy & Security -> Accessibility`
- `Privacy & Security -> Screen Recording`

改完权限后重启终端，再跑 `doctor`。能看到微信窗口坐标就可以采集。

## 输出

每次运行生成：

```text
runs/YYYYMMDD-HHMMSS/
```

重点看：

- `summary.md`：摘要和主要话题
- `chat_clean.md`：去重后的聊天文本
- `screenshots/`：原始截图，用来检查是否截偏或混入其他窗口

如果发现截图混入终端窗口、图片预览窗口，先把微信聊天窗口置前并关闭浮层，再重新采集。

## 常用调参

更完整但更慢：

```bash
./run_wechat.sh --screens 140 --quality precise --scroll-amount 3
```

滚动太少：

```bash
./run_wechat.sh --screens 80 --scroll-amount 8
```

滚轮不生效：

```bash
./run_wechat.sh --screens 40 --scroll-method pageup --scroll-amount 1
```

截图边缘缺字，调裁剪 `left,top,right,bottom`：

```bash
./run_wechat.sh --screens 80 --quality precise --crop 320,70,10,100
```

OCR 不准时，优先试更高放大倍率；默认是 `--ocr-mode best --ocr-scale 1.5`：

```bash
./run_wechat.sh --screens 80 --quality precise --ocr-mode best --ocr-scale 1.8
```

如果增强后反而误识别，可退回原图 OCR：

```bash
./run_wechat.sh --screens 80 --quality precise --ocr-mode raw --ocr-scale 1.0
```

默认不会点击聊天内容，避免点开图片/视频。只有必须点击聚焦时才用：

```bash
./run_wechat.sh --screens 40 --focus-click
```

## 已有截图

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --python 3.12 python wechat_analyzer.py ocr /path/to/screenshots
UV_CACHE_DIR=/private/tmp/uv-cache uv run --python 3.12 python wechat_analyzer.py summarize /path/to/screenshots
```

## 清理

预览清理：

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --python 3.12 python wechat_analyzer.py cleanup --runs-dir /Users/sun/Documents/Mac-pro/wechat-chat-mvp/runs --older-than-days 14 --keep-latest 10
```

真正删除：

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --python 3.12 python wechat_analyzer.py cleanup --runs-dir /Users/sun/Documents/Mac-pro/wechat-chat-mvp/runs --older-than-days 14 --keep-latest 10 --yes
```

清空所有历史记录：

```bash
UV_CACHE_DIR=/private/tmp/uv-cache uv run --python 3.12 python wechat_analyzer.py cleanup --runs-dir /Users/sun/Documents/Mac-pro/wechat-chat-mvp/runs --older-than-days 0 --keep-latest 0 --yes
```

## 隐私

`runs/` 下的 `summary.md`、`chat_clean.md`、`ocr_raw.json` 和截图都可能包含明文聊天内容，不要提交到 git 或分享给别人。

## Agent 工作流

本项目已加入 AI agent 工作流规则，入口文件是：

```text
AGENTS.md
```

当前项目目录还不是 git 仓库时，可以先用本地任务模式测试：

```bash
scripts/run-local-agent-task.sh docs/sample-local-agent-task.md
```

接入 GitHub 仓库后，可以使用 GitHub Issue / PR 模式：

```bash
scripts/validate-agent-task.sh 123
scripts/route-agent-task.sh 123
scripts/run-agent-task.sh 123
```

注意：agent 不应读取、提交或上传 `runs/` 下的聊天截图、OCR 文本、清洗文本或摘要，除非任务明确要求做本地结果检查。
