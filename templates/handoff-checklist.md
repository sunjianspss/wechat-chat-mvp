# 接入检查清单

## 入口

- [ ] 选择入口：Slack / 飞书 / Coze / 多维表
- [ ] 入口消息可以触发 webhook
- [ ] webhook 可以创建 GitHub Issue 或飞书任务
- [ ] 创建 Issue 时使用 `Agent Task` 模板

## 任务

- [ ] Issue 必须包含背景、目标、验收标准、限制条件
- [ ] Issue 自动添加 `agent-task` 和 `needs-routing`
- [ ] 缺少验收标准时添加 `missing-acceptance-criteria`
- [ ] 涉及生产、权限、密钥、账单时添加 `needs-human`

## Agent

- [ ] 本地或远程 runner 已安装所需 CLI
- [ ] runner 已安装 `gh`、`git`、`ruby`
- [ ] runner 已登录 GitHub CLI，或配置了 `GH_TOKEN`
- [ ] runner 有仓库读取权限
- [ ] runner 可以创建分支或 worktree
- [ ] runner 可以创建 PR
- [ ] runner 不具备生产部署权限
- [ ] `scripts/validate-agent-task.sh <issue>` 可以通过
- [ ] `scripts/route-agent-task.sh <issue>` 可以输出 agent
- [ ] `scripts/run-agent-task.sh <issue>` 可以创建 worktree

## CI/CD

- [ ] PR 会自动运行测试
- [ ] PR 会自动运行构建
- [ ] 没有项目测试命令时 CI 必须失败
- [ ] CI 失败时会通知 agent 或群
- [ ] 生产部署必须手动触发
- [ ] 有回滚方案

## 通知

- [ ] PR 创建后通知群
- [ ] CI 通过后通知群
- [ ] CI 失败后通知群
- [ ] 需要人工确认时明确 @ 负责人
- [ ] 完成通知使用 `templates/done-notification.md`
