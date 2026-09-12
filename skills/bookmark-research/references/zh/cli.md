# CLI 与调用示例

[English](../cli.md) · **中文阅读版**

所有命令使用 Python 3.9+ 标准库，stdout 为 JSON。把 `<root>` 替换为本插件实际绝对路径。包路径、来源名、公司名、节点 ID 和 example.com URL 均为占位示例，使用时替换为用户输入或实际查询结果。插件没有预置这些来源或书签。`--db` 与 `--config` 是全局参数，须放在子命令之前。MCP 提供相同核心能力；CLI 是 Pi 或未接 MCP 载体的执行入口。

```sh
python3 <root>/src/cli.py doctor
python3 <root>/src/cli.py sync /absolute/path/to/package --source-id my-canvas
python3 <root>/src/cli.py status
python3 <root>/src/cli.py search my-canvas --target '示例公司甲' --target '示例公司乙' --section A --limit 5
python3 <root>/src/cli.py search my-canvas --group card-group-example --limit 50
python3 <root>/src/cli.py context my-canvas --group card-group-example
python3 <root>/src/cli.py context my-canvas --item actual-bookmark-id
```

`sync` 接受目录、ZIP 或单卡 JSON；`--mode snapshot` 保存快照，`--mode live` 绑定持续目录。`--completeness partial` 保留未提供文件，明确完整镜像才用 `complete`。新普通导出默认 snapshot、Git 目录默认 live；已有来源沿用原模式。同一画布的新导出沿用 `--source-id`。完整说明见 [来源生命周期](source-lifecycle.md)。

`history <source-id>` 列出内容版本与可恢复的快照路径。MCP 运行期间自动检查 live 来源；只用终端时可运行 `watch`，前台持续检查并输出状态变化的 JSON 行。

`search` 同时匹配标题、URL、note、tag 和文件夹路径。多个 `--tag` 为同时满足；多个 `--target` 各自计算结果并返回并集。它不提供任意 SQL 执行。默认 refresh 检查 live 来源的文件哈希；snapshot 不读取原下载位置。`--no-refresh` 使用当前已同步索引，不能选择某个历史版本。查询返回的 `source.state` 区分固定快照、已同步、待更新和失败状态；CLI 的兼容字段 `stored_snapshot_only` 仍只表示跳过主动检查。

`context` 不传 `--item` 时只返回栏目头、画布节点和关系，`items:[]` 不代表栏目为空。取文件夹 ID 可先 `search` 找到其中一个书签，再 `context --item <书签ID>` 读取 `ancestors`，随后用 `search --folder <文件夹ID>` 限定范围。`--section` 匹配重复 label 时可能选择多个栏目，单张卡片应传唯一 ID。

数据库优先级：`--db` → `BOOKMARK_RESEARCH_DATA_DIR/index.sqlite3` → `${XDG_DATA_HOME:-~/.local/share}/bookmark-research/index.sqlite3`。CLI 与各客户端设相同路径即可共用一个索引。数据库不能放在原始同步包或插件代码目录内。

```sh
python3 <root>/src/cli.py providers
python3 <root>/src/cli.py providers --probe
python3 <root>/src/cli.py search-web --target '示例公司甲 官方价格' --target '示例公司乙 官方价格' --limit 5
python3 <root>/src/cli.py fetch-web https://example.com/company-a https://example.com/company-b
python3 <root>/src/cli.py fetch-web https://example.com/company-a --no-archive --max-characters 30000
python3 <root>/src/cli.py config show
python3 <root>/src/cli.py config set --search-provider exa --archive true
python3 <root>/src/cli.py config set --archive-dir /absolute/path/to/knowledge
```

`config show` / `config set` 对应 MCP `get_settings` / `update_settings`。`config set --input /path/to/changes.json`（或 `-` 从 stdin）支持合并部分配置。CLI 标志覆盖同次 JSON 输入中的对应字段。`fetch-web` 默认归档，`--archive` / `--no-archive` 只覆盖本次；后续调用的默认值用 `config set --archive true|false`。其他配置与目录优先级见 [配置与归档](settings-and-archive.md)。

`providers` 只描述配置；`--probe` 才联网检查握手和工具列表。Exa/Parallel 公共端点是否可匿名使用取决于服务当前限额；可在启动进程前设置 `EXA_API_KEY` / `PARALLEL_API_KEY`。可选 `--provider tavily`：存在 `TAVILY_API_KEY` 时使用 Bearer，否则发送明确 keyless header。工具列出不证明当前凭据能够执行。不要把密钥写进 manifest 或报告。

独立目标标签与多轮查询可通过 `search-web --input /path/to/query.json` 传入：

```json
{
  "targets": [
    {"target": "示例公司甲", "query": "示例公司甲 官方 API 价格"},
    {"target": "示例公司甲", "query": "示例公司甲 官方产品文档"},
    {"target": "示例公司乙", "query": "示例公司乙 官方 API 价格"}
  ],
  "providers": ["exa", "parallel"],
  "limit_per_target": 5
}
```

上限为 12 个 target/query 对、每目标 20 个返回 URL；`fetch-web` 每次最多 8 个 URL。provider 之间并行，同一 provider 的会话按序处理并复用工具目录。

融合载体上其他 MCP 的**实际结果**：将结果规范成下面形状，调用 `merge-results /path/to/batches.json`。不要凭摘要补造 URL、排名或 provider 名。

```json
{
  "targets": ["示例公司甲"],
  "limit_per_target": 5,
  "batches": [{
    "provider": "tavily",
    "target": "示例公司甲",
    "query": "示例公司甲 官方 API 价格",
    "status": "ok",
    "results": [{"url": "https://example.com/company-a", "title": "示例公司甲", "snippet": "此处替换为服务实际返回的摘要", "rank": 1}]
  }]
}
```

失败批次用 `status:"error"`、`results:[]`、`error` 描述；空成功结果则用 `status:"ok"`、`results:[]`。结果中的 `coverage`、`uncovered_targets`、`errors` 用于区分覆盖不足与调用失败。

## 深度研究命令

`research record <research-id> --input <entry.json>` 的 entry 可用 `{"kind":"resume","text":"继续调查已记录的缺口"}`，恢复已导出 incomplete 报告的任务；原报告和预算都会保留。

当前模型负责决策和综合，CLI 保存状态并执行每个步骤。先读 [深度研究流程](deep-research.md)，其中含 brief、预算、引用和 record 各类型的完整参数约定。

```sh
python3 <root>/src/cli.py research start --input /path/to/brief.json
python3 <root>/src/cli.py research status
python3 <root>/src/cli.py research status <research-id>
python3 <root>/src/cli.py research status <research-id> --section claims --offset 0 --limit 20
python3 <root>/src/cli.py research inventory <research-id> --offset 0 --limit 100
python3 <root>/src/cli.py research coverage <research-id> --filter unreviewed --offset 0 --limit 100
python3 <root>/src/cli.py research search <research-id> --input /path/to/search-step.json
python3 <root>/src/cli.py research fetch <research-id> --input /path/to/fetch-step.json
python3 <root>/src/cli.py research source <research-id> s1 --offset 0 --limit 12000
python3 <root>/src/cli.py research import-evidence <research-id> --input /path/to/actual-evidence.json
python3 <root>/src/cli.py research record <research-id> --input /path/to/entry.json
python3 <root>/src/cli.py research finish <research-id> --summary '已核验的结论' --status completed
```

`--input -` 从 stdin 读 JSON。start 的 JSON 同 `research_start` 参数；search/fetch 的 JSON 使用对应 MCP 字段但省略位置参数已传的 `research_id`；record 的 JSON **仅包含 entry 对象**，例如 `{kind:"gap",question_id:"q1",text:"尚缺一手资料"}` 的标准 JSON 写法。finish 支持重复 `--limitation`；未完成使用 `--status incomplete`，取消用 `cancelled`。

默认研究目录与 MCP 相同，位于数据目录 `research/`。CLI 可在 `research` 之后、动作之前传 `--directory /absolute/path/to/research`。换会话时保持该目录一致，按 `status` 返回的 ID 和正文继续。网络步骤要求 `operation_id`，重用同一 ID 读取结果不会重复提交。运行 `research start/status/source/record/finish` 不需要 API key 或网络。

`source_ids` 是真实已同步的包 ID，start 默认冻结完整范围。inventory 与 coverage 必须读取到 next_offset 为 null；`--inventory-id` 可重复指定一批原 URL ID。import-evidence 的 JSON 同 MCP 但省略位置参数里的 research_id，必须是真实正文和 provenance；外部报告不会增加原页覆盖率。

## 宿主路由与专业研究服务

```sh
python3 <root>/src/cli.py research route --host codex --task-shape batch_research --tool collaboration.spawn_agent
python3 <root>/src/cli.py research route --host claude_code --available-command /bookmark-research:bookmark-research
python3 <root>/src/cli.py research service describe
python3 <root>/src/cli.py research service prepare --input /path/to/service-brief.json
python3 <root>/src/cli.py research service start --input /path/to/service-request-with-operation-id.json
python3 <root>/src/cli.py research service status <external-id> --refresh
python3 <root>/src/cli.py research service result <external-id> --offset 0 --limit 12000
python3 <root>/src/cli.py research service attach --input /path/to/known-run.json
python3 <root>/src/cli.py research service import <external-id> --operation-id import-report
python3 <root>/src/cli.py research service cancel <external-id>
```

route 的 `--tool`、`--available-command`、`--extension` 可重复；填当前会话真实观察值，也可 `--input` 使用完整 MCP 参数。路由不执行工作流。prepare/start/attach JSON 包含 research_id；服务创建、查询、取消的语义见 [专业研究服务](research-services.md)。描述和准备不联网，`--refresh` 只观察已有远端任务一次；不要把超时后新建任务当作恢复。

## Wiki 与评测

```sh
python3 <root>/src/cli.py wiki write <page-id> --input /path/to/page-and-change-note.json
python3 <root>/src/cli.py wiki get <page-id>
python3 <root>/src/cli.py wiki get <page-id> --revision 1
python3 <root>/src/cli.py wiki list --offset 0 --limit 20
python3 <root>/src/cli.py wiki search '研究执行' --limit 10
python3 <root>/src/cli.py wiki lint
python3 <root>/src/cli.py evaluate --input /path/to/suite-runs-judgments.json
```

wiki write 输入为 `{page,change_note,expected_revision?}`，page_id 已由位置参数提供；更新须传当前 revision。Wiki 可在动作前加 `--directory`，非默认研究目录用 `--research-directory` 指定。evaluate 接收 `{suite,runs,judgments?}`，计算真实提供的数据，不自动启动模型评审。格式与质量边界见 [Wiki 与评测](wiki-and-evaluation.md)。
