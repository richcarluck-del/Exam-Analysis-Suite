# DeepSeek Worker Runtime 接口与目录规范

本文档是 [deepseek-worker-runtime-design.md](D:/10739/Exam-Analysis-Suite/docs/deepseek-worker-runtime-design.md) 的工程实现补充。

目标：

- 给开发方提供明确的目录结构
- 给出 MCP 工具接口的 JSON Schema
- 统一任务、状态、日志、产物的数据结构
- 降低实现分歧，避免交付时出现“能跑但不符合 Codex 调度需要”的情况

## 1. 目录结构规范

推荐项目结构如下：

```text
deepseek-worker-runtime/
  package.json                     # 或 pyproject.toml
  README.md
  .env.example
  src/
    mcp/
      server.ts                    # MCP server 入口
      tools/
        start_worker_job.ts
        get_worker_status.ts
        get_worker_result.ts
        cancel_worker_job.ts
    runtime/
      agent_loop.ts
      action_dispatcher.ts
      action_parser.ts
      task_executor.ts
      verification.ts
    workspace/
      worktree_manager.ts
      path_guard.ts
    tools/
      file_tools.ts
      search_tools.ts
      command_tools.ts
      git_tools.ts
    storage/
      jobs_store.ts
      artifacts_store.ts
      events_store.ts
    schemas/
      task_card.schema.json
      start_worker_job.schema.json
      worker_status.schema.json
      worker_result.schema.json
    security/
      command_policy.ts
      network_policy.ts
    providers/
      deepseek_client.ts
    utils/
      logger.ts
      time.ts
      ids.ts
  data/
    jobs/
    artifacts/
    worktrees/
  tests/
    contract/
    integration/
    fixtures/
```

### 1.1 强约束

必须满足：

- `src/mcp/server.*` 为 MCP 入口
- `src/schemas/` 下保留 JSON Schema
- `data/jobs/` 保存任务状态
- `data/artifacts/` 保存命令输出、diff、报告
- `data/worktrees/` 保存任务工作区

### 1.2 不允许省略的目录

这些目录不得缺失：

- `mcp/`
- `runtime/`
- `workspace/`
- `tools/`
- `storage/`
- `schemas/`
- `security/`

原因：如果这些层混在一起，后续很难稳定扩展多 worker 或权限控制。

## 2. 通用字段规范

### 2.1 标识符

#### `job_id`

格式建议：

```text
job_<YYYYMMDD>_<6位递增或随机串>
```

示例：

```text
job_20260509_000123
```

#### `command_id`

格式建议：

```text
cmd_<job_id>_<seq>
```

#### `artifact_id`

格式建议：

```text
artifact_<job_id>_<seq>
```

## 3. 核心枚举规范

### 3.1 Job 状态

```json
[
  "queued",
  "preparing_workspace",
  "loading_context",
  "planning",
  "acting",
  "observing",
  "verifying",
  "repairing",
  "blocked",
  "failed",
  "completed",
  "cancelled"
]
```

### 3.2 网络模式

```json
[
  "off",
  "allowlist",
  "full"
]
```

### 3.3 命令执行状态

```json
[
  "running",
  "completed",
  "failed",
  "timed_out",
  "killed"
]
```

### 3.4 事件类型

```json
[
  "job_created",
  "workspace_prepared",
  "round_started",
  "action_dispatched",
  "action_completed",
  "command_started",
  "command_completed",
  "verification_started",
  "verification_completed",
  "job_blocked",
  "job_failed",
  "job_completed",
  "job_cancelled"
]
```

## 4. Task Card Schema

文件：

`src/schemas/task_card.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "task_card.schema.json",
  "title": "TaskCard",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "title",
    "goal",
    "acceptance_criteria"
  ],
  "properties": {
    "title": {
      "type": "string",
      "minLength": 1
    },
    "goal": {
      "type": "string",
      "minLength": 1
    },
    "context": {
      "type": "array",
      "items": { "type": "string" },
      "default": []
    },
    "acceptance_criteria": {
      "type": "array",
      "minItems": 1,
      "items": { "type": "string" }
    },
    "constraints": {
      "type": "array",
      "items": { "type": "string" },
      "default": []
    },
    "preferred_files": {
      "type": "array",
      "items": { "type": "string" },
      "default": []
    },
    "verification_commands": {
      "type": "array",
      "items": { "type": "string" },
      "default": []
    }
  }
}
```

## 5. `start_worker_job` 输入 Schema

文件：

`src/schemas/start_worker_job.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "start_worker_job.schema.json",
  "title": "StartWorkerJobInput",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "task_card",
    "repo_path",
    "worktree_path",
    "allowed_paths",
    "allowed_commands",
    "network_mode",
    "timeout_minutes",
    "max_rounds"
  ],
  "properties": {
    "task_card": {
      "$ref": "task_card.schema.json"
    },
    "repo_path": {
      "type": "string",
      "minLength": 1
    },
    "worktree_path": {
      "type": "string",
      "minLength": 1
    },
    "base_ref": {
      "type": "string",
      "default": "HEAD"
    },
    "allowed_paths": {
      "type": "array",
      "minItems": 1,
      "items": { "type": "string" }
    },
    "allowed_commands": {
      "type": "array",
      "minItems": 1,
      "items": { "type": "string" }
    },
    "network_mode": {
      "type": "string",
      "enum": ["off", "allowlist", "full"]
    },
    "network_allowlist": {
      "type": "array",
      "items": { "type": "string" },
      "default": []
    },
    "timeout_minutes": {
      "type": "integer",
      "minimum": 1,
      "maximum": 240
    },
    "max_rounds": {
      "type": "integer",
      "minimum": 1,
      "maximum": 100
    },
    "model": {
      "type": "string"
    },
    "env": {
      "type": "object",
      "additionalProperties": {
        "type": "string"
      },
      "default": {}
    }
  }
}
```

### 5.1 `start_worker_job` 返回结构

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["job_id", "status"],
  "properties": {
    "job_id": { "type": "string" },
    "status": {
      "type": "string",
      "enum": ["queued"]
    }
  }
}
```

## 6. `get_worker_status` 返回 Schema

文件：

`src/schemas/worker_status.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "worker_status.schema.json",
  "title": "WorkerStatus",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "job_id",
    "status",
    "phase",
    "round",
    "files_touched",
    "commands_run_count",
    "started_at",
    "updated_at"
  ],
  "properties": {
    "job_id": { "type": "string" },
    "status": {
      "type": "string",
      "enum": [
        "queued",
        "preparing_workspace",
        "loading_context",
        "planning",
        "acting",
        "observing",
        "verifying",
        "repairing",
        "blocked",
        "failed",
        "completed",
        "cancelled"
      ]
    },
    "phase": { "type": "string" },
    "round": {
      "type": "integer",
      "minimum": 0
    },
    "last_action": {
      "type": ["string", "null"]
    },
    "files_touched": {
      "type": "array",
      "items": { "type": "string" }
    },
    "commands_run_count": {
      "type": "integer",
      "minimum": 0
    },
    "started_at": {
      "type": "string",
      "format": "date-time"
    },
    "updated_at": {
      "type": "string",
      "format": "date-time"
    },
    "blocked_reason": {
      "type": ["string", "null"]
    },
    "failure_reason": {
      "type": ["string", "null"]
    }
  }
}
```

## 7. `get_worker_result` 返回 Schema

文件：

`src/schemas/worker_result.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "worker_result.schema.json",
  "title": "WorkerResult",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "job_id",
    "status",
    "summary",
    "files_changed",
    "commands_run",
    "test_results",
    "git_diff_artifact",
    "final_report_artifact",
    "worktree_path"
  ],
  "properties": {
    "job_id": { "type": "string" },
    "status": {
      "type": "string",
      "enum": ["completed", "failed", "blocked", "cancelled"]
    },
    "summary": { "type": "string" },
    "files_changed": {
      "type": "array",
      "items": { "type": "string" }
    },
    "commands_run": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "command_id",
          "command",
          "cwd",
          "exit_code",
          "status",
          "duration_ms",
          "stdout_artifact",
          "stderr_artifact"
        ],
        "properties": {
          "command_id": { "type": "string" },
          "command": { "type": "string" },
          "cwd": { "type": "string" },
          "exit_code": { "type": ["integer", "null"] },
          "status": {
            "type": "string",
            "enum": ["completed", "failed", "timed_out", "killed"]
          },
          "duration_ms": {
            "type": "integer",
            "minimum": 0
          },
          "stdout_artifact": { "type": "string" },
          "stderr_artifact": { "type": "string" }
        }
      }
    },
    "test_results": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["name", "status"],
        "properties": {
          "name": { "type": "string" },
          "status": {
            "type": "string",
            "enum": ["passed", "failed", "skipped", "unknown"]
          },
          "details": { "type": ["string", "null"] }
        }
      }
    },
    "git_diff_artifact": { "type": "string" },
    "final_report_artifact": { "type": "string" },
    "worktree_path": { "type": "string" },
    "failure_reason": { "type": ["string", "null"] },
    "blocked_reason": { "type": ["string", "null"] }
  }
}
```

## 8. Job 持久化文件规范

每个 job 对应一个目录：

```text
data/jobs/<job_id>/
  job.json
  status.json
  events.jsonl
  commands.json
  result.json
```

### 8.1 `job.json`

保存原始任务输入。

示例：

```json
{
  "job_id": "job_20260509_000123",
  "created_at": "2026-05-09T10:00:00+08:00",
  "task_card": { "...": "..." },
  "repo_path": "D:/10739/Exam-Analysis-Suite",
  "worktree_path": "D:/10739/Exam-Analysis-Suite/.worktrees/job_20260509_000123",
  "allowed_paths": [
    "D:/10739/Exam-Analysis-Suite/analyzer"
  ],
  "allowed_commands": [
    "python",
    "pytest",
    "git",
    "rg"
  ],
  "network_mode": "off",
  "max_rounds": 20,
  "timeout_minutes": 45,
  "model": "deepseek-v4-pro"
}
```

### 8.2 `status.json`

保存当前状态快照。

示例：

```json
{
  "job_id": "job_20260509_000123",
  "status": "verifying",
  "phase": "verifying",
  "round": 6,
  "last_action": "run_command pytest analyzer/tests/test_related_relations.py",
  "files_touched": [
    "analyzer/app/knowledge_point_parser.py"
  ],
  "commands_run_count": 3,
  "started_at": "2026-05-09T10:00:01+08:00",
  "updated_at": "2026-05-09T10:08:55+08:00",
  "blocked_reason": null,
  "failure_reason": null
}
```

### 8.3 `events.jsonl`

一行一个事件，必须可顺序回放。

示例：

```json
{"ts":"2026-05-09T10:00:01+08:00","event_type":"job_created","job_id":"job_20260509_000123","payload":{"status":"queued"}}
{"ts":"2026-05-09T10:00:04+08:00","event_type":"workspace_prepared","job_id":"job_20260509_000123","payload":{"worktree_path":"D:/10739/Exam-Analysis-Suite/.worktrees/job_20260509_000123"}}
{"ts":"2026-05-09T10:01:10+08:00","event_type":"command_started","job_id":"job_20260509_000123","payload":{"command_id":"cmd_job_20260509_000123_01","command":"git status"}}
```

### 8.4 `commands.json`

记录所有命令元数据。

### 8.5 `result.json`

完成后写入，与 `worker_result.schema.json` 一致。

## 9. Artifacts 目录规范

每个 job 的产物目录：

```text
data/artifacts/<job_id>/
  prompt_round_01.json
  prompt_round_02.json
  cmd_01.stdout.txt
  cmd_01.stderr.txt
  cmd_02.stdout.txt
  cmd_02.stderr.txt
  final.diff
  final_report.md
```

### 9.1 最低要求

这些文件必须存在：

- `final.diff`
- `final_report.md`
- 至少一份命令输出文件（如果跑过命令）

## 10. Worktree 目录规范

推荐：

```text
data/worktrees/<job_id>/
```

或由调用方传入：

```text
<repo>/.worktrees/<job_id>/
```

要求：

- job 结束后默认保留
- 由外部显式清理
- 不允许自动删除，避免丢失审查现场

## 11. 命令白名单规范

建议用“命令前缀匹配”，不要只做字符串 contains。

### 11.1 示例策略

允许：

```json
[
  ["python"],
  ["pytest"],
  ["rg"],
  ["git", "status"],
  ["git", "diff"],
  ["git", "add"],
  ["node"],
  ["npm", "test"]
]
```

拒绝：

```json
[
  ["git", "push"],
  ["git", "reset", "--hard"],
  ["rm"],
  ["del"],
  ["docker"],
  ["psql"],
  ["curl"],
  ["Invoke-WebRequest"]
]
```

### 11.2 必须具备的命令校验逻辑

- 标准化切词
- 路径参数检查
- 工作目录限制
- 超时限制
- 输出字节上限

## 12. 路径保护规范

所有文件动作必须做：

1. 绝对路径归一化
2. 检查是否在 `allowed_paths` 内
3. 拒绝符号链接逃逸
4. 拒绝 `..` 越界

如果失败：

- 动作返回拒绝
- 记 `action_dispatched` 与 `action_completed` 失败日志
- 任务进入 `blocked` 或继续下一轮由模型修正

## 13. MCP 工具响应规范

所有工具必须返回结构化 JSON 对象，不允许只返回自然语言。

### 13.1 错误格式

统一格式：

```json
{
  "error": {
    "code": "JOB_NOT_FOUND",
    "message": "job_id job_20260509_000123 does not exist"
  }
}
```

错误码建议：

- `VALIDATION_ERROR`
- `JOB_NOT_FOUND`
- `JOB_NOT_FINISHED`
- `WORKSPACE_PREPARE_FAILED`
- `PERMISSION_DENIED`
- `COMMAND_NOT_ALLOWED`
- `INTERNAL_ERROR`

## 14. 最低测试要求

开发方必须至少写以下测试：

### 14.1 Contract Tests

- `start_worker_job` 输入校验
- `get_worker_status` 返回结构校验
- `get_worker_result` 返回结构校验
- 错误格式校验

### 14.2 Integration Tests

- 创建 worktree
- 写文件并读回
- 跑命令并记录输出
- 生成 diff
- 非法路径拦截
- 非法命令拦截

## 15. 最终交付清单

开发方交付时，必须给出：

1. 运行说明
2. `.env.example`
3. MCP 工具清单
4. JSON Schema 文件
5. 一个最小演示任务
6. 一份真实执行产生的 `result.json`
7. 一份真实执行产生的 `final.diff`

## 16. 交付判定标准

只有在以下条件同时满足时，才算接口实现合格：

1. Schema 文件完整且实际返回结构一致
2. 目录结构与文档一致
3. Worker 能独立修改代码并回传 diff
4. Worker 能独立运行命令并回传日志
5. Codex 侧只靠 MCP 接口就能调度，不需要人工补步骤

不满足其中任一项，都不算可投入实际项目使用。
