# 三个宿主，共用三项基础能力

Codex、Claude Code、DeepSeek Harness 负责推理、工具选择、并发和最终表达。插件保留三项职责：

1. **上下文**：读取 JSON Canvas 节点、连接线、卡片与空间关系。时间信息保留来源与可信度；Git 历史直接交给宿主 shell。
2. **外部调研**：已知 URL 直接读取；Agentic Search 由宿主判断缺口并迭代搜索／阅读，插件提供补充搜索、并发抓取与归档。Deep Research 可直接提交 OpenAI／Parallel API，无需本地研究会话。宿主已有的浏览器、爬虫或研究工具也可供稿。
3. **LLM Wiki**：检索已有知识，一次提交正文与精确引用，保留来源、修订和页面关系，供后续调研复用。

日常流程是：**取上下文 → 独立检索 Wiki／归档 → 阅读与搜索 → 宿主形成结论 → 按授权保存 Wiki**。`plan_research` 只提供候选，既不设相关性硬门槛，也不决定研究路线；没有书签命中仍会查询其他存储。默认工具面为 21 个。

只有明确要求整包覆盖、持久化任务或中断后续做时，启用 `deep` 预设的完整 43 个工具及分组工作流。高级功能复用现有证据与存储；普通提问不要求经过 readiness、route、inventory 或 coverage 等阶段。

Wiki 一次写入采用 `page.sections[].citations` 与顶层 `sources`，也兼容旧的 research claim 引用格式。程序校验引文与来源完整性，语义支持由宿主或人工审阅。API 报告是二手来源，关键结论仍应核查原文。
