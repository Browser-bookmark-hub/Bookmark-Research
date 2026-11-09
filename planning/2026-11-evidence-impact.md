# 证据链影响面（impact）计划书

> 2026-11-10 · 依据：CodeGraph 的 `impact`/`affected` 设计 + 本仓库 CodeGraph 索引（154 文件 / 4,216 节点 / 13,596 边）
> 目标：回答“改这个来源/URL/文件，除了 Wiki，还有哪些书签、研究、报告、归档和任务要复核”。

## 0. 一句话

把散落在 `source_freshness`、`_coverage`、`_affected` 里的依赖检查，收敛成一个只读的 `br impact`（CLI 优先，deep MCP 可选），覆盖整条证据链，而不是只看 Wiki。

## 1. 证据链（代码事实）

```
Canvas 包 / 书签 / URL / Git
   │
   ├─ BookmarkIndex.input_version / inventory        src/bookmark_index.py:2281 / :2194
   ├─ SourceVersions.snapshots / checks              src/source_versions.py:11
   ├─ ref_codec 短 ref（绑定 source version）        src/ref_codec.py:24 / :53
   ├─ SourceArchive captures / body sha256           src/archive.py:181 / :700 / :749
   │
   ├─ ResearchSessions.source_freshness              src/research.py:696
   ├─ ResearchSessions.inventory                     src/research.py:784
   ├─ ResearchSessions._coverage → ResearchCoverage  src/research.py:804 / src/research_coverage.py:99
   ├─ finish: report.md / sources.json / coverage    src/research.py:1674 起
   │
   ├─ WikiStore._affected → WikiSearchIndex.affected src/wiki.py:924 / src/wiki_search.py:148
   ├─ WikiStore._issues / refresh                    src/wiki.py:206 / :955
   │
   └─ JobStore.list（pending 输入）                  src/jobs.py:239
```

CodeGraph 的 `impact <symbol>` 和 `affected [files]` 之所以强，是因为 symbol → caller → test 都有边。我们这条链也有边，只是没有统一的反向索引。

## 2. 现状：哪些有、哪些没有

| 层 | 已有能力 | 缺口 |
|---|---|---|
| Canvas | `input_version`、`inventory`、`source_status` | 没有“URL → 哪些 item/ref”的反查 |
| 短 ref | `ref_codec` 版本绑定，过期报 `stale_ref` | 没有“哪些 ref 因这次变更过期”的清单 |
| 归档 | capture body sha256、freshness | 没有“capture → 哪些 claim/页面”的反查 |
| 研究 | `source_freshness` 逐任务比较冻结 scope；`_coverage` 逐 URL 检查 | 没有跨任务的 URL → claim 反查；报告没有依赖清单 |
| 报告 | `report.md`、`sources.json`、`coverage-*.json` | 没登记它依赖哪些 claim / 原始 URL |
| Wiki | `_affected` 算直接页 + linked 页；`_issues` 检查引用 | 不含 research/report；只按 URL，不含 source_id/file |
| 任务 | `jobs.list` 可看状态 | 不按输入 URL 反查 |

所以“除了 Wiki 没有影响吗”的答案是：**有，但只有 Wiki 建了反向索引。**

## 3. impact 的对象模型

输入（互斥，至少一个）：

| 参数 | 解析 |
|---|---|
| `--source-id` | `BookmarkIndex.resolve_source_id`，取该 source 的当前版本 |
| `--url` | `SourceArchive._key` 规范化后匹配 |
| `--file` | source 的 `files` 表 → 受影响 item/section |
| `--capture-id` | archive capture → body sha256 → 引用它的 source/claim |
| `--research-id` | 该任务的 claims / inventory / 报告 |
| `--page-id` | 该 Wiki 页 + linked 页 |

输出：

```jsonc
{
  "input": {"kind": "url", "value": "https://example.com/a", "canonical": "..."},
  "canvas": {
    "sources": [{"source_id","version_id","state","changed":true}],
    "items": [{"source_id","section_id","item_id","ref","folder_path"}],
    "stale_refs": [{"ref","reason":"source_version_changed"}]
  },
  "archive": [{"capture_id","url","sha256","retrieved_at","stale":true}],
  "research": [{
    "research_id","status","inventory_ids","claim_ids",
    "freshness":{"state":"changed","requires_review":true},
    "coverage":{"missing":0,"unread":1,"unreviewed":2}
  }],
  "reports": [{"research_id","report","sources","coverage_file"}],
  "wiki": [{"page_id","revision","reason":"direct_citation|linked_page","status":"needs_review"}],
  "jobs": [{"job_id","kind","state","matches":["payload.url"]}],
  "summary": {"direct": 5, "transitive": 9, "stale": 2, "requires_review": 3}
}
```

规则：

- **只读**：不抓网页、不写索引、不改研究/Wiki；
- **直接 vs 传递**：`--depth` 控制 Wiki linked 页和 Canvas 依赖的传递层数；
- **找不到不等于没影响**：报告 `searched` 范围（sources/research/wiki/jobs 数量）和 `unreadable` 清单；
- **规范化 URL**：所有 URL 用 `SourceArchive._key` 比较，避免尾斜杠/大小写误判。

## 4. 实现分期

### P1：URL / source 的只读扫描（先做）

- CLI `br impact --url ...` / `--source-id ... --json`；
- 扫描范围：当前索引、`research/` 任务（114 个）、Wiki index、jobs；
- 复用 `source_freshness`、`_coverage`、`_affected`，不新写业务规则；
- 预算：5,006 条书签、114 个研究任务、13 个 Wiki 页，目标 < 1s；输出分页/上限。

### P2：file / capture / research / page

- `--file` 走 source `files` 表 → item/section；
- `--capture-id` 走 archive → 引用它的 source（`inventory_ids` / citation hash）；
- `--research-id` 直接给该任务的 claims/报告/覆盖；
- `--page-id` 给页面 + linked 页。

### P3：反向索引（性能）

新增可重建的 `impact.sqlite3`（派生，不权威）：

```
url_consumers(url, kind, id, detail)
source_deps(source_id, kind, id)
claim_reports(research_id, claim_id, report_file)
capture_consumers(capture_id, kind, id)
```

- 在 `sync_package`、`research_import_evidence`、`research_finish`、`wiki write` 后增量更新；
- 失败不影响主流程；`impact` 在索引不可用时退回扫描（像 `_affected` 的 fallback）。

### P4：入口

- CLI 为主；
- deep MCP 可选 `impact`（不进默认 10 原语）；
- Skill 加一句“改来源前先 `br impact`”。

## 5. 验收

- 给定一个 URL，能列出：书签实例、相关研究任务/claims、报告文件、Wiki 直接页 + linked 页、pending jobs；
- 给定一个 source，能列出 `stale_refs` 和需要复核的页面；
- 所有结果带 `searched` 范围与 `unreadable`；
- 5,006 条书签 + 114 任务 + 13 页面：扫描 < 1s；有反向索引 < 100ms；
- 全量测试通过；不新增默认 MCP 工具。

## 6. 非目标

- 不自动修复、不自动刷新、不写 Wiki；
- 不抓网页；
- 不做 Git 内容 diff（Git 时间线仍归宿主 shell）；
- 不把 `impact` 放进 quick 目录。

## 7. CodeGraph 对照

| CodeGraph | 本插件 |
|---|---|
| `impact <symbol>` | `br impact --url/--source-id` |
| `affected [files]` | `--file` → items/research/wiki |
| per-file staleness banner | 结果级 `freshness` / `stale_refs` |
| `status --strict` | `impact.summary.requires_review` |
| 索引 + fallback | `impact.sqlite3` + 扫描 fallback |
| MCP 单工具 | CLI 优先；impact 只进 deep |
