# Superteam 使用指南

## 工作流总览

```
1. 需求分析 → working/spec.md
2. /superteam:planning → working/plan/
3. /superteam:executing → working/commit-message.md + working/task-summary.md
```

## Step 1: 需求分析

用任意方式产出 spec，写入 `working/spec.md`。

可用手段：
- `/superpowers:brainstorming`
- plan mode
- 手写

spec 需包含：目标、架构、技术栈。

## Step 2: 规划

在对话中输入：

```
/superteam:planning
```

状态机流程：

1. 检查 `working/spec.md` 存在
2. 等待你确认后分发 `planner` → 产出 `working/plan/task-NNN/task.md`
3. 自动分发 `plan-reviewer` → 产出 `working/plan-review-results.md`
4. 有 Pending issues → 重新分发 planner 修复 → 再次 review
5. 循环直到 0 Pending → 完成

## Step 3: 执行

```
/superteam:executing
```

状态机对每个 task 串行执行：

```
Task 001:
  implementer (TDD)
  → spec-reviewer ┐
  → code-reviewer ┘
  → 有 Pending issues → 重派 implementer
  → 0 Pending → 下一个

Task 002:
  ...

Task NNN 完成后:
  → 生成 working/commit-message.md
  → 生成 working/task-summary.md
```

每个 task 循环细节：

1. dispatch `implementer`（TDD 实现 + 测试）
2. 检查 `test-results.md` → 非 `EXPECTED` 则重派 implementer
3. 测试通过后并行 dispatch `spec-reviewer` + `code-reviewer`
4. 检查 `implement-review-results.md` → 有 Pending 则重派 implementer
5. 无 Pending → 下一个 task

## 文件约定

| 文件 | 用途 |
|------|------|
| `working/spec.md` | 需求规格 |
| `working/plan/task-NNN/task.md` | 任务文档 |
| `working/plan-review-results.md` | 计划审核结果 |
| `working/plan/task-NNN/changes.md` | 任务变更记录 |
| `working/plan/task-NNN/test-results.md` | 测试结果 |
| `working/plan/task-NNN/implement-review-results.md` | 实现审核结果 |
| `working/commit-message.md` | 最终 commit message |
| `working/task-summary.md` | 任务总结 |
| `working/spec-issues.md` | 规格问题（自动生成） |
| `working/plan-issues.md` | 计划问题（自动生成） |
| `working/env-issues.md` | 环境问题（自动生成） |

## 中断恢复

ctrl-c 中断后重新启动，告诉 agent 从第 N 个 task 继续即可。文件系统保留全部进度。

## Agents

| Agent | 职责 |
|-------|------|
| `planner` | 根据 spec 创建任务文档 |
| `plan-reviewer` | 审核任务文档完整性和 spec 对齐 |
| `implementer` | TDD 实现单个 task + 修复 issues |
| `spec-reviewer` | 审核实现是否符合 task 要求 |
| `code-reviewer` | 审核代码质量 |

## 核心原则

- 主 agent = 状态机，不思考、不判断、不解释
- Sub-agent 通过文件系统沟通（读/写 `working/` 下约定文件）
- 每次 sub-agent 调用 = 全新 context，从文件读取信息
- 所有 reviewer 不限次数，通过文件持久化 issues 保证收敛
- 黑盒测试与功能实现分离为独立 task，遵循 TDD
