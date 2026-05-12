# DeepSeek Worker Runtime 技术设计

## 1. 目标

构建一个可被 Codex 通过 MCP 调用的 DeepSeek Worker Runtime。

目标状态：

- Codex 负责总路线、任务拆解、最终验收。
- DeepSeek Worker 负责独立执行：
  - 读取代码与配置
  - 搜索文件与符号
  - 修改文件
  - 执行命令
  - 运行测试与自检
  - 输出变更结果与执行报告
- Codex 不再代替 Worker 落代码。

这不是普通的 `chat` MCP，而是一个强制性执行型 agent runtime。

## 2. 非目标

本设计不追求：

- 让 DeepSeek 在规划和验收能力上等同 Codex
- 让 Worker 直接操作生产环境
- 一开始就支持无限并行 worker
- 一开始就支持任意网络访问和任意 shell 权限

## 3. 核心原则

1. 执行能力必须完整，避免因为缺能力而把活回流给 Codex。
2. Worker 必须有独立工作区，不能默认直写主工作区。
3. 所有动作必须可审计、可回放、可终止。
4. Codex 只通过 MCP 调度 Worker，不直接介入 Worker 的具体执行步骤。
5. Worker 的能力强，但权限必须受控。

## 4. 总体架构

```text
Codex / Supervisor
    |
    | MCP tools
    v
DeepSeek Worker Runtime
    |
    +-- Task Store
    +-- Workspace Manager (git worktree)
    +-- Tool Executor
    +-- DeepSeek Agent Loop
    +-- Artifact / Log Store
```

### 4.1 组件说明

#### A. Codex / Supervisor

职责：

- 定义任务目标
- 指定约束和验收标准
- 启动 worker job
- 轮询状态
- 读取结果
- 决定接受、返工、取消

#### B. DeepSeek Worker Runtime

职责：

- 接收结构化任务卡
- 创建独立 worktree / workspace
- 驱动 DeepSeek 进入 agent loop
- 将模型输出解析为内部动作
- 执行动作
- 记录日志
- 收敛到 `completed / failed / blocked / cancelled`

#### C. Task Store

保存：

- job 元数据
- 当前状态
- 动作历史
- 输出日志
- 结果摘要
- 最终 diff / 文件清单 / 测试结果

建议初期用 SQLite + JSONL，后续可换 PostgreSQL。

#### D. Workspace Manager

职责：

- 为每个任务创建独立工作目录
- 推荐默认使用 `git worktree`
- 允许指定基准分支或 commit
- 任务结束后保留现场用于审查

## 5. 推荐部署形态

### 5.1 推荐方案

- Runtime 部署在本机或内网机器
- Runtime 以 MCP server 形式提供能力
- 每个任务分配独立 `git worktree`

### 5.2 不推荐方案

- 直接给 Worker 主工作区写权限
- 允许 Worker 在整个磁盘任意读写
- 允许 Worker 直接跑生产数据库命令

## 6. 能力要求

这是本设计最重要的部分。能力面必须一次定义完整。

### 6.1 基础文件能力

Worker 内部必须具备：

- `read_file`
- `read_files_batch`
- `write_file`
- `apply_patch`
- `append_file`
- `list_dir`
- `glob_files`
- `search_text`
- `stat_path`
- `move_path`
- `delete_path`（仅限工作区内、默认关闭）

### 6.2 代码理解能力

建议具备：

- `rg` / ripgrep 搜索
- symbol 级搜索（可后补）
- `git diff`
- `git status`
- 最近修改文件查看

### 6.3 命令执行能力

必须具备：

- `run_command`
- `read_command_output`
- `kill_command`

命令执行要求：

- 支持超时
- 支持 stdout/stderr 截断
- 支持返回 exit code
- 支持后台进程标记

### 6.4 Git 能力

必须具备：

- `git_status`
- `git_diff`

建议具备：

- `git_add`
- `git_commit`（默认关闭）

明确禁止默认开放：

- `git push`
- `git reset --hard`
- `git checkout --`
- 对主工作区直接 destructive 操作

### 6.5 测试与验证能力

必须具备：

- 能运行项目测试命令
- 能运行 lint / type check / smoke script
- 能读取测试报告或控制台输出

### 6.6 任务结果能力

必须输出：

- 修改文件列表
- 执行命令列表
- 测试结果
- 最终摘要
- 失败原因
- 最终 diff

## 7. Worker Runtime 的 MCP 接口

MCP 暴露给 Codex 的工具建议如下。

### 7.1 `start_worker_job`

输入：

```json
{
  "task_card": {
    "title": "收紧 KP-KP related 关系质量",
    "goal": "只处理 related 关系的质量收口，不改数据库 schema",
    "context": [
      "项目根目录: D:/10739/Exam-Analysis-Suite",
      "目标包: 438, 444",
      "代码优先级高于文档"
    ],
    "acceptance_criteria": [
      "只修改 related relation 相关逻辑",
      "可运行回归脚本",
      "输出修改文件清单、命令、结果"
    ],
    "constraints": [
      "不得修改 alembic migration",
      "不得访问生产数据库",
      "不得改主工作区"
    ]
  },
  "repo_path": "D:/10739/Exam-Analysis-Suite",
  "worktree_path": "D:/10739/Exam-Analysis-Suite/.worktrees/worker-job-001",
  "base_ref": "HEAD",
  "allowed_paths": [
    "D:/10739/Exam-Analysis-Suite/analyzer",
    "D:/10739/Exam-Analysis-Suite/shared",
    "D:/10739/Exam-Analysis-Suite/scripts",
    "D:/10739/Exam-Analysis-Suite/docs"
  ],
  "allowed_commands": [
    "python",
    "pytest",
    "rg",
    "git"
  ],
  "network_mode": "off",
  "timeout_minutes": 45,
  "max_rounds": 20,
  "model": "deepseek-v4-pro"
}
```

输出：

```json
{
  "job_id": "job_20260509_001",
  "status": "queued"
}
```

### 7.2 `get_worker_status`

输入：

```json
{
  "job_id": "job_20260509_001"
}
```

输出：

```json
{
  "job_id": "job_20260509_001",
  "status": "running",
  "phase": "verify",
  "round": 8,
  "last_action": "run_command pytest analyzer/tests/test_related_relations.py",
  "files_touched": [
    "analyzer/app/knowledge_point_parser.py",
    "scripts/kp_relations_package_audit.py"
  ],
  "commands_run_count": 5,
  "started_at": "2026-05-09T10:00:00+08:00",
  "updated_at": "2026-05-09T10:12:05+08:00"
}
```

### 7.3 `get_worker_result`

输入：

```json
{
  "job_id": "job_20260509_001"
}
```

输出：

```json
{
  "job_id": "job_20260509_001",
  "status": "completed",
  "summary": "收紧 related 关系接纳规则并补充审计输出字段。",
  "files_changed": [
    "analyzer/app/knowledge_point_parser.py",
    "scripts/kp_relations_package_audit.py",
    "docs/topic-ingest-quality-plan-20260508.md"
  ],
  "commands_run": [
    {
      "command": "python scripts/kp_relations_package_audit.py --package-id 438",
      "exit_code": 0,
      "duration_ms": 1432,
      "stdout_artifact": "artifacts/job_20260509_001/cmd_03.stdout.txt",
      "stderr_artifact": "artifacts/job_20260509_001/cmd_03.stderr.txt"
    }
  ],
  "test_results": [
    {
      "name": "package_438_audit",
      "status": "passed"
    }
  ],
  "git_diff_artifact": "artifacts/job_20260509_001/final.diff",
  "final_report_artifact": "artifacts/job_20260509_001/final_report.md",
  "worktree_path": "D:/10739/Exam-Analysis-Suite/.worktrees/worker-job-001"
}
```

### 7.4 `cancel_worker_job`

输入：

```json
{
  "job_id": "job_20260509_001"
}
```

输出：

```json
{
  "job_id": "job_20260509_001",
  "cancelled": true
}
```

### 7.5 可选增强工具

建议后续增加：

- `list_worker_jobs`
- `stream_worker_log`
- `get_worker_artifact`
- `submit_worker_feedback`
- `resume_worker_job`

## 8. Worker 内部动作协议

Runtime 内部不应直接把所有能力暴露给 Codex。  
这些动作是给 DeepSeek agent loop 用的。

建议动作集合：

- `read_file(path)`
- `read_files_batch(paths[])`
- `write_file(path, content)`
- `apply_patch(path, patch)`
- `list_dir(path)`
- `glob_files(pattern, base_path)`
- `search_text(pattern, base_path, max_results)`
- `run_command(command, cwd, timeout_ms)`
- `read_command_output(command_id)`
- `kill_command(command_id)`
- `git_status(cwd)`
- `git_diff(cwd, paths[])`
- `finish(summary)`
- `block(reason)`
- `fail(reason)`

内部实现不强制要求模型输出 XML。  
可以用 JSON action，也可以用函数调用风格。  
关键要求只有两个：

1. 模型输出必须可机器解析
2. Runtime 必须循环执行直到完成或失败

## 9. Agent Loop 设计

### 9.1 状态机

```text
RECEIVED
  -> PREPARE_WORKSPACE
  -> LOAD_CONTEXT
  -> PLAN
  -> ACT
  -> OBSERVE
  -> VERIFY
  -> REPAIR (可回到 ACT)
  -> DONE | BLOCKED | FAILED | CANCELLED
```

### 9.2 关键行为

#### PLAN

Worker 先理解任务卡和仓库约束，不直接动手。

#### ACT

Worker 执行读写文件、搜索、修改、命令执行。

#### OBSERVE

Worker 读取动作结果，更新下一轮策略。

#### VERIFY

Worker 必须自己跑验证，而不是只说“应该可以”。

#### REPAIR

如果测试失败，Worker 必须有自修复循环。

### 9.3 终止条件

满足以下任一条件终止：

- 达成验收标准
- 显式 `BLOCKED`
- 显式 `FAILED`
- 超过 `max_rounds`
- 超过 `timeout_minutes`
- 被外部取消

## 10. 独立工作区策略

必须支持：

- 基于 `repo_path + base_ref` 创建 `git worktree`
- 每个 job 一个独立目录
- job 结束后保留 worktree 供 Codex 审查

推荐目录：

```text
.worker_runtime/
  jobs/
    job_20260509_001/
      job.json
      events.jsonl
      artifacts/
  worktrees/
    job_20260509_001/
```

不建议默认在主仓库直接执行。

## 11. 权限模型

### 11.1 路径权限

所有文件动作必须受 `allowed_paths` 限制。

规则：

- 只允许访问 `allowed_paths` 子树
- 禁止访问用户目录其他位置
- 禁止访问系统目录

### 11.2 命令权限

所有命令必须命中白名单。

建议初始支持：

- `python`
- `pytest`
- `rg`
- `git status`
- `git diff`
- `git add`
- `npm test`
- `node`

需要显式禁用或审批：

- `rm -rf`
- `del /s`
- `git push`
- `docker`
- `psql`
- `curl`
- `Invoke-WebRequest`

### 11.3 网络权限

建议三档：

- `off`
- `allowlist`
- `full`

默认 `off`。

## 12. 审计与可观测性

每个 job 必须落审计日志：

- 每轮 prompt 摘要
- 每个动作
- 每个命令
- 命令输出位置
- 最终状态

推荐产物：

- `events.jsonl`
- `prompt_round_*.json`
- `cmd_*.stdout.txt`
- `cmd_*.stderr.txt`
- `final.diff`
- `final_report.md`

## 13. 失败与阻塞处理

Worker 必须区分：

- `FAILED`
  - 代码修改失败
  - 命令执行失败且无法修复
  - 内部异常

- `BLOCKED`
  - 权限不足
  - 缺少文件
  - 依赖未安装
  - 任务卡信息不足

`BLOCKED` 必须带可执行的阻塞原因，不允许只返回泛泛描述。

## 14. 与 Codex 的协作约定

Codex 作为 leader，只依赖 MCP 工具，不进入 Worker 内部细节。

推荐工作流：

1. Codex 本地分析问题并拆任务
2. Codex 调 `start_worker_job`
3. Codex 轮询 `get_worker_status`
4. Codex 取 `get_worker_result`
5. Codex 基于 diff / 测试结果验收
6. Codex 再决定下一轮派工

这意味着 Worker 的返回信息必须足够完整，不能只有一句自然语言总结。

## 15. 技术实现建议

### 15.1 推荐栈

- Runtime 语言：Node.js 或 Python
- MCP server：标准 MCP tool server
- Task Store：SQLite + JSONL
- Workspace：`git worktree`
- DeepSeek：官方 API

### 15.2 不建议的实现

- 只实现一个 `worker_chat(text)` 返回文本
- 没有独立 worktree
- 没有命令白名单
- 没有最终 diff 和测试结果

## 16. 分阶段交付

### Phase 1: 最小可用版

必须完成：

- MCP 4 个核心工具
- 单 worker job
- 独立 worktree
- 文件读写
- 命令执行
- 结果回传

### Phase 2: 工程化版

增加：

- 流式日志
- `resume`
- `feedback`
- 后台任务管理
- 更细粒度权限模型

### Phase 3: 并行版

增加：

- 多 worker 并行
- job 队列
- 冲突检测
- worker 资源限制

## 17. 验收用例

开发方交付时，至少通过以下用例。

### Case 1: 文件写入闭环

任务：

- 在指定 worktree 下创建文件
- 读取回写内容
- 输出结果

通过标准：

- 文件真实存在
- 返回文件路径和内容校验结果

### Case 2: 代码修改闭环

任务：

- 读一个已有模块
- 按任务卡要求做小改动
- 生成 diff

通过标准：

- diff 正确
- 只改 allowed path

### Case 3: 测试闭环

任务：

- 修改代码
- 运行测试命令
- 失败后至少尝试一次修复

通过标准：

- 命令日志完整
- 测试结果真实可追溯

### Case 4: 权限阻断

任务：

- 让 Worker 访问工作区外路径或执行禁用命令

通过标准：

- 被拒绝
- 状态为 `blocked` 或 `failed`
- 审计日志可见

### Case 5: Codex 对接闭环

任务：

- Codex 通过 MCP 调用 `start_worker_job`
- 轮询状态
- 获取结果

通过标准：

- 4 个核心 MCP 工具全部可用
- job 生命周期完整

## 18. 对开发方的硬性要求

1. 不允许交一个只有文本聊天能力的假 worker。
2. 不允许缺 `git diff`、命令执行、结果回传这类关键能力。
3. 不允许直接默认写主工作区。
4. 不允许没有命令和路径边界。
5. 不允许没有日志和可审计产物。

## 19. 最终验收标准

只有在满足以下条件后，才算 Runtime 可用于本项目：

1. Codex 可以通过 MCP 发任务、查状态、取结果
2. DeepSeek Worker 可以独立读代码、改代码、跑命令、自检
3. Worker 结果包含完整 diff、命令记录、测试结果
4. Worker 默认在独立 worktree 内工作
5. 权限边界和审计日志可用

做到这 5 条，才能进入项目实际使用阶段。
