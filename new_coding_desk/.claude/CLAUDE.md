1. **必须**遵守 @docs\ 下所有文档要求、接口规范
2. 大改动前先git push
3. 完成任务时主agent只负责决策，任务必须分给 Sub-agent

# Superteam 工作流

本工程使用 superteam 状态机驱动开发。主 agent 不思考、不判断，只机械执行流程。

## 启动流程

1. 需求分析 → 产出 `working/spec.md`
2. `/superteam:planning` → 产出 `working/plan/`
3. `/superteam:executing` → 产出 `working/commit-message.md` + `working/task-summary.md`

## 核心原则

- 主 agent = 状态机，禁止解释/判断/总结
- Sub-agent 通过文件系统沟通（读/写 working/ 下约定文件）
- 每次 sub-agent 调用 = 全新 context，从文件读取信息
- 所有 reviewer 不限 review 次数，通过文件持久化 issues 保证收敛
- 黑盒测试验证最终产出
