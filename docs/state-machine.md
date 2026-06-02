# Agent Task State Machine

这份状态机用于把“群聊消息 -> Issue -> agent 开发 -> PR -> CI -> 通知”落成可执行规则。

## 状态标签

| 状态 | GitHub Label | 含义 | 下一步 |
| --- | --- | --- | --- |
| 待补充 | `missing-acceptance-criteria` | 缺少验收标准 | 人类补充 Issue |
| 需要人工 | `needs-human` | 涉及权限、密钥、生产、账单或需求不清 | 人类处理 |
| 待路由 | `needs-routing` | Issue 已创建，等待选择 agent | 运行路由脚本 |
| 已路由 | `agent-routed` | 已确定 agent | 启动 runner |
| 开发中 | `agent-running` | agent 正在 worktree 中开发 | 等待 PR |
| PR 已创建 | `pr-created` | agent 已提交 PR | 等待 CI |
| CI 失败 | `ci-failed` | 自动检查失败 | agent 最多修复 3 轮 |
| 等待 review | `needs-review` | CI 通过，需要人工 review | 人类 review |
| 已合并 | `merged` | PR 已 merge | 可申请部署 |
| 待部署 | `deploy-requested` | 请求部署 | 人类触发部署 |
| 已完成 | `done` | 已通知群，任务闭环 | 无 |

## 强制拦截

以下标签存在时，agent runner 不得启动：

```text
needs-human
missing-acceptance-criteria
blocked
```

对应脚本：

```text
scripts/validate-agent-task.sh
scripts/route-agent-task.sh
```

## 状态流转

```text
message_received
  -> issue_created + needs-routing
  -> validate-agent-task
  -> route-agent-task + agent-routed
  -> run-agent-task + agent-running
  -> pr_created
  -> ci_passed + needs-review
  -> human_merge
  -> deploy_requested
  -> manual_deploy
  -> notify_done + done
```

## 失败流转

```text
missing_required_fields
  -> missing-acceptance-criteria
  -> human_updates_issue
  -> needs-routing

ci_failed
  -> ci-failed
  -> agent_retry
  -> max 3 rounds
  -> needs-human

security_or_permission_risk
  -> needs-human
  -> no agent execution
```

## 责任边界

| 动作 | 责任方 |
| --- | --- |
| 提出需求 | 人类 |
| 整理 Issue | intake bot |
| 补充验收标准 | 人类 |
| 路由 agent | route script / orchestrator |
| 写代码 | coding agent |
| 跑测试 | agent + CI |
| review | 人类或独立 reviewer agent |
| merge | 人类 |
| 生产部署 | 人类触发 |
| 完成通知 | notify script / bot |
