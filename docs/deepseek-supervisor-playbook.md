# DeepSeek Supervisor Playbook

This playbook turns the Codex plus DeepSeek setup into an execution rule set instead of an informal habit.

## 1. Routing rules

Every meaningful task should be classified into one of three routes before work starts.

### Route A: `local`

Use `local` when any of these are true:

- The task takes less than 10 minutes.
- The task depends on real local code execution, databases, logs, or files.
- The task is high-risk or irreversible.
- The main difficulty is judgment, not drafting.

Examples:

- applying a migration
- inspecting a live ingestion result
- comparing database state with code behavior
- making final architecture choices

### Route B: `delegate`

Use `delegate` when all of these are true:

- The task can be expressed as a bounded prompt.
- The output can be reviewed quickly.
- The first pass does not need hidden local context.

Examples:

- first-pass implementation plan
- draft test matrix
- candidate extraction rules
- prompt rewrite
- code review on a pasted file slice

### Route C: `hybrid`

Use `hybrid` when the task has two layers:

- Codex keeps the high-risk or context-heavy layer.
- DeepSeek handles one reviewable sidecar task.

Examples:

- Codex inspects runtime state while DeepSeek drafts fallback heuristics.
- Codex decides API design while DeepSeek proposes test cases.
- Codex performs the real patch while DeepSeek critiques one module.

## 2. Delegation scorecard

Before sending a task to DeepSeek, score it quickly:

- Context visibility: can DeepSeek see enough to do a good first pass?
- Review cost: can Codex verify the answer in under 3 minutes?
- Failure cost: if the answer is wrong, is the damage low?

Delegate only if:

- context visibility is high
- review cost is low
- failure cost is low or moderate

Otherwise keep it local.

## 3. Mandatory supervisor loop

For each delegated step, Codex should follow this order:

1. Restate the goal locally.
2. Define one narrow subtask.
3. Define acceptance criteria.
4. Send the subtask to DeepSeek.
5. Review the answer against local facts.
6. Choose one action: accept, revise once, or take over locally.

Do not chain multiple vague requests to DeepSeek without a review checkpoint.

## 4. Standard prompt template

Use this structure whenever possible:

```text
Goal:
<overall objective>

Subtask:
<one narrow thing to do now>

Input:
<only the facts, code, or constraints needed>

Acceptance:
- <criterion 1>
- <criterion 2>
- <criterion 3>

Output format:
<exact format required>
```

## 5. Standard review template

After a DeepSeek response, Codex should check:

```text
Review result:
- Correct scope: yes/no
- Grounded in provided facts: yes/no
- Actionable output: yes/no
- Conflicts with local evidence: yes/no
- Needs revision: yes/no
```

If `Needs revision` is yes, send one targeted correction request. If the second attempt still drifts, switch to `local`.

## 6. Task classes and defaults

| Task class | Default route | Notes |
|---|---|---|
| Small code fix | local | Faster to do directly |
| Broad brainstorming | delegate | Keep output format strict |
| First-pass review | delegate | Verify locally before acting |
| DB or runtime diagnosis | local | Needs real environment |
| Large feature with clear slices | hybrid | Split execution and judgment |
| Final write-up after real analysis | hybrid | Draft can be delegated, truth-check stays local |

## 7. Hard boundaries

Do not let DeepSeek directly decide:

- schema changes
- production operations
- destructive cleanup
- final acceptance of code or analysis
- claims about data it did not actually inspect

## 8. How this saves tokens

This setup saves Codex-side tokens when DeepSeek handles:

- first drafts
- long paraphrases
- alternative options
- repetitive transformation work

It does not help much when:

- the task is tiny
- the answer requires hidden local context
- review is as expensive as doing the work

## 9. Practical operating rule

Use this default unless there is a good reason not to:

- plan locally
- delegate one bounded first pass
- review locally
- revise once at most
- finish locally

That pattern keeps the supervisor role strong and prevents the system from turning into unreviewed outsourcing.
