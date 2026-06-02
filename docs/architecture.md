# AI Agent Workflow Architecture

这份架构图描述 `ai-agent-workflow` 如何把群聊需求变成可追踪、可验收、可交付的 agent 研发任务。

## Overall Architecture

```mermaid
flowchart LR
  User["Human requester"] --> Chat["Slack / Feishu / Coze"]
  Chat --> Intake["Intake bot<br/>prompts/issue-intake.md"]
  Intake --> Issue["GitHub Issue<br/>Agent Task template"]

  Issue --> Validate["Validate task<br/>scripts/validate-agent-task.sh"]
  Validate -->|ready| Route["Route task<br/>scripts/route-agent-task.sh"]
  Validate -->|blocked| Human["Human clarification"]

  Route --> Config["Routing config<br/>config/agent-routing.yml"]
  Config --> Runner["Agent runner<br/>scripts/run-agent-task.sh"]

  Runner --> Worktree["Isolated git worktree"]
  Worktree --> Agent["Coding agent<br/>Codex / Kimi / DeepSeek"]
  Agent --> PR["Pull Request"]

  PR --> CI["Agent CI<br/>.github/workflows/agent-ci.yml"]
  CI -->|passed| Review["Human review"]
  CI -->|failed| Fix["Agent retry<br/>max 3 rounds"]
  Fix --> PR

  Review -->|approved| Merge["Human merge"]
  Merge --> DeployGate["Manual deploy gate<br/>deploy-gate.yml"]
  DeployGate --> Notify["Done notification<br/>scripts/notify-done.sh"]
  Notify --> Chat
```

## Component Boundaries

```mermaid
flowchart TB
  subgraph Entry["Entry Layer"]
    Chat2["Slack / Feishu / Coze"]
    IntakePrompt["prompts/issue-intake.md"]
  end

  subgraph Task["Task Layer"]
    IssueTemplate[".github/ISSUE_TEMPLATE/agent-task.yml"]
    StateMachine["docs/state-machine.md"]
    RoutingConfig["config/agent-routing.yml"]
  end

  subgraph Execution["Execution Layer"]
    Validator["scripts/validate-agent-task.sh"]
    Router["scripts/route-agent-task.sh"]
    Runner2["scripts/run-agent-task.sh"]
    AgentPrompt["prompts/agent-run.md"]
    Agents["Codex / Kimi / DeepSeek"]
  end

  subgraph Delivery["Delivery Layer"]
    CI2[".github/workflows/agent-ci.yml"]
    Deploy[".github/workflows/deploy-gate.yml"]
    Notify2["scripts/notify-done.sh"]
  end

  Chat2 --> IntakePrompt
  IntakePrompt --> IssueTemplate
  IssueTemplate --> Validator
  StateMachine --> Validator
  Validator --> Router
  RoutingConfig --> Router
  Router --> Runner2
  AgentPrompt --> Runner2
  Runner2 --> Agents
  Agents --> CI2
  CI2 --> Deploy
  CI2 --> Notify2
```

## State Flow

```mermaid
stateDiagram-v2
  [*] --> needs_routing: issue_created

  needs_routing --> missing_acceptance_criteria: required fields missing
  needs_routing --> needs_human: risky or unclear task
  needs_routing --> agent_routed: validation passed

  missing_acceptance_criteria --> needs_routing: human updates issue
  needs_human --> needs_routing: human approves or clarifies

  agent_routed --> agent_running: runner starts
  agent_running --> pr_created: agent opens PR
  pr_created --> ci_failed: CI failed
  pr_created --> needs_review: CI passed

  ci_failed --> agent_running: retry <= 3
  ci_failed --> needs_human: retry limit reached

  needs_review --> merged: human approves
  merged --> deploy_requested: release requested
  deploy_requested --> deployed: manual deploy approved
  deployed --> done: notification sent
  done --> [*]
```

## Local Runner Sequence

```mermaid
sequenceDiagram
  participant Human
  participant GH as GitHub Issue
  participant Validate as validate-agent-task.sh
  participant Route as route-agent-task.sh
  participant Runner as run-agent-task.sh
  participant Agent as Coding Agent
  participant CI as GitHub Actions

  Human->>GH: Create or approve Agent Task
  Human->>Validate: validate issue number
  Validate->>GH: Read body and labels
  Validate-->>Human: Ready or blocked
  Human->>Route: route issue number
  Route->>GH: Read labels
  Route-->>Human: Agent decision
  Human->>Runner: prepare worktree
  Runner->>GH: Read issue title, URL, body
  Runner->>Runner: Create branch and worktree
  Runner->>Agent: Provide generated prompt
  Agent->>GH: Create PR
  GH->>CI: Trigger PR checks
  CI-->>Human: passed / failed
```

## Security Gates

```mermaid
flowchart TD
  TaskText["Issue body / comments"] --> Gate1{"Has required sections?"}
  Gate1 -->|no| Block1["Block<br/>missing-acceptance-criteria"]
  Gate1 -->|yes| Gate2{"Has blocked labels?"}

  Gate2 -->|yes| Block2["Block<br/>needs-human / blocked"]
  Gate2 -->|no| Gate3{"Prompt-injection or bypass text?"}

  Gate3 -->|yes| Block3["Block<br/>manual review"]
  Gate3 -->|no| Gate4{"PR links Issue?"}

  Gate4 -->|no| Block4["Fail CI"]
  Gate4 -->|yes| Gate5{"Project checks configured?"}

  Gate5 -->|no| Block5["Fail CI"]
  Gate5 -->|yes| Allow["Allow human review"]

  Allow --> MergeGate["Human merge only"]
  MergeGate --> DeployGate["Manual deploy gate"]
```
