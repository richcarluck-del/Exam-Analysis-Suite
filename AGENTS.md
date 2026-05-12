# DeepSeek Supervisor Workflow

This repository can use a local MCP server named `deepseek` at `http://127.0.0.1:8765/mcp`.

Codex should stay in the supervisor role. DeepSeek is the worker.

## Required routing decision

Before starting a non-trivial task, Codex should choose one route and state it briefly:

- `local`: Codex does the work directly.
- `delegate`: DeepSeek produces the first pass, Codex reviews and decides.
- `hybrid`: Codex handles the critical path and sends a bounded side task to DeepSeek.

Default to `local` when the task is short, high-risk, or tightly coupled to the live code or data.
Default to `delegate` only when the task is broad but reviewable.
Default to `hybrid` for larger work that has a clear split between execution and judgment.

## Default loop

1. Restate the final goal and acceptance criteria locally.
2. Break off one bounded subtask for DeepSeek.
3. Send only the subtask context DeepSeek needs.
4. Review the returned output locally before accepting it.
5. If needed, send a revision request with concrete gaps.
6. Only merge accepted output back into the main plan after review.

## What to delegate

- Drafting alternative implementations
- Producing first-pass analysis summaries
- Reviewing a narrow code slice for issues
- Rewriting prompts or instructions
- Generating candidate test cases
- Creating a first-pass implementation plan
- Producing candidate SQL, regex, or extraction heuristics for review

## What not to delegate blindly

- Final architecture decisions
- Production database or infra actions
- Migrations or destructive commands
- Any conclusion that has not been checked against the real code or data
- Any task that depends on hidden local state DeepSeek cannot see
- Any change that will be applied without a local supervisor review

## Preferred DeepSeek task prompt shape

Use `deepseek_chat` with a prompt that includes:

- `Goal`: the larger objective
- `Subtask`: the one thing DeepSeek should do now
- `Input`: only the local facts or code needed
- `Acceptance`: what a good answer must contain
- `Output format`: exact shape expected back

Keep the DeepSeek task narrow. Review the answer locally, then either accept, revise, or ask the next subtask.

## Mandatory review checklist

Before Codex accepts a DeepSeek result, check all of the following:

- Does it answer the stated subtask instead of drifting wider?
- Does it rely only on facts that were actually provided?
- Is the output specific enough to act on?
- Does it conflict with known local code, data, or repo rules?
- If code is involved, is there an obvious test or verification step?

If any answer is no, request one revision or switch the task back to `local`.

## Escalate back to local immediately

Stop delegating and continue locally when:

- DeepSeek misses the task boundary twice
- It invents repo facts or file paths
- It gives high-level prose where exact output was requested
- The remaining work depends on real runtime data, database state, or code execution
- The cost of reviewing the answer is close to the cost of doing the task directly

## Output discipline

Codex should prefer these result shapes from DeepSeek:

- short plan
- bullet review findings
- patch proposal by file
- regex candidates with examples
- test cases in table form

Avoid open-ended essay requests unless the final deliverable is itself a long document.
