# Bookmark Research 0.4.0 validation

Version 0.4.0 combines whole-package research, host workflows, optional professional research, Wiki/evaluation, source lifecycle management and English/Chinese instructions. Earlier unpublished 0.3.0 work is included in this version; original validation measurements retain their observed versions and limits. A passing code test, a recognized plugin manifest and a successful model-driven workflow are separate observations.

Manual export folders can disappear, and a later export can have a different filename or location. Stable source identity is separate from input paths, snapshots are recoverable, and explicitly persistent directories can be monitored. Directory, ZIP and single-card input use the existing Bookmark Canvas export protocol.

## Implemented behavior

- Directory, wrapped/unwrapped ZIP, and permanent/temporary section JSON input. Unknown fields, exact raw protocol bytes, bookmark instances and relationships are retained. Ambiguous multi-package archives and loose cards mixed into a package fail visibly instead of reducing the imported scope.
- `snapshot` and `live` source modes, persistent path aliases, immutable content versions and `source_history`. The current exported protocol has no reliable global canvas ID; moved exports of the same canvas reuse an explicit `source_id`, and distinct canvases are not merged by titles or URLs.
- Separate `partial` and `complete` deletion rules. Single cards are partial inputs. Full mirrors remove absent files while preserving stable item identity through renames. Empty directories, Git write locks and invalid/inconsistent files retain the last valid index.
- A process-scoped Python polling monitor, separate SQLite connections, consistent query reads, debounced updates, a longer deletion grace period, visible pending/error states and reconnect/query checks. Monitoring stops when the MCP process stops; standalone CLI users can run `watch`.
- Full managed snapshots after partial imports, including recorded relationships needed to recover an older layout after a card-only rename. Recovery validates hashes. Legacy JSON recovered only from SQLite is explicitly labeled as lacking original whitespace.
- Research status compares frozen scope with current indexed input. Wiki reads/lint flag changed bookmark input for review. No automatic webpage fetch, LLM research, evidence rewrite or Wiki publication is performed.
- Installation discovery probes use an isolated empty data directory, so verifying an installation cannot start monitoring the user's sources. First-use instructions describe the supported input forms and continuous-directory mode.

## Whole-package scope

The supplied package was read offline through the same index and research inventory APIs. Independent counts and the frozen inventory agree: **223 bookmark instances, 207 distinct original URL strings, 22 folders, 4 sections, 5 canvas nodes and 4 group memberships**. This package has no directed edges; the synthetic fixture separately exercises directed edges and copy cards.

All three inventory pages were consumed and compared with the complete indexed inventory. Every original instance remains mapped to its URL and context. All nine files in the original directory had identical SHA-256 hashes before and after validation. Personal source files, paths and inventory contents are not included in the distribution.

For 207 URLs, the default fetch plan reports a 26-call lower bound at eight URLs per call and a 38-call configured budget. Explicit user budgets remain unchanged. A budget below the first-pass capacity reports the shortfall without removing sources. This verifies data handling and capacity accounting; it does not mean all 207 webpages were fetched or reviewed during this offline check.

Both professional-service payloads were also prepared offline from this actual frozen input. Each retains all 207 inventory IDs: 206 HTTP(S) URLs are supplied as retrievable sources and one `file://` input remains explicitly local-only. Nothing was submitted. A regression checks 207 URLs/223 instances, an explicit 150-ID subproblem and oversized private context without reducing source scope or uploading notes.

## Automated verification

The consolidated 0.4.0 tree passed **319 tests** in 34.511 seconds, including 63 JavaScript host workflow contract scenarios. Plugin/Skill validators and local document-path checks passed. The plugin manifest, local MCP server identity and remote MCP client identity all use 0.4.0; exporters derive their package versions from the manifest.

The source-lifecycle checkpoint passed **313 tests** on Python 3.9.6 / SQLite 3.43.2 with FTS5. This includes 32 source-lifecycle cases and 20 installer cases. The source-lifecycle module was also run independently after the final consistency adjustment, and the installer module was run independently to verify it does not depend on test discovery order.

```sh
python3 -B -m unittest discover -s tests -v
python3 -B -m unittest discover -s tests -p 'test_source_manager.py'
python3 -B -m unittest discover -s tests -p 'test_install.py'
```

Cases cover persistent reopen, changed paths, duplicate source ambiguity, single-card merge, raw-byte recovery, renamed layout bindings, corrupt snapshots, ZIP traversal/symlinks/duplicates/multiple roots/size bounds, full-mirror deletion, partial retention, temporary directory loss, Git locks, changes during import, idle background updates, MCP reconnect, frozen research scope, Wiki review flags, and CLI/MCP behavior. The host workflow, research service and coverage regressions remain included.

Skill/plugin validation and `git diff --check` passed. These checks establish implementation behavior and packaging validity, not semantic research quality.

The tests cover full inventories, explicit subsets, repeated URLs, original context, concurrent evidence writes, legacy state, pagination, rejected evidence, partial review, external reports, unknown service outcomes and completion gates. Reviewing only part of the input cannot complete a whole-package investigation. Accounted items, accepted text, substantive review and answered questions have separate denominators.

MCP/CLI integration tests establish a complete research session, cross interface boundaries when reading and importing, reject partial completion, and publish/search/lint a Wiki page from accepted evidence. They also check routing, settings and evaluation parity. The evaluation fixture is synthetic; its scores make no provider-quality claim. The earlier host/research checkpoint passed 280 tests, including 19 service lifecycle tests and 19 installer tests; its host wrapper exercised 36 JavaScript scenarios. These are checkpoint measurements, not the final combined test count.

```sh
python3 -B -m unittest discover -s tests -v
python3 -B scripts/verify_fixture.py --output /absolute/external/new-directory
python3 -B scripts/verify_quality.py
python3 -B -m unittest discover -s tests -p 'test_host_workflows.py'
```

Append `--package /absolute/path/to/package` to the fixture verifier for read-only validation of a real package. Use a new output directory outside source packages and plugin caches. The fixture deliberately retains blocked sources and produces an incomplete report, proving that complete accounting is not complete research.

## English and Chinese instructions

The execution Skill and all 11 method references are maintained in English, with 12 complete Chinese reading copies. There is one discoverable Skill. Starter prompts and onboarding are bilingual; Codex delegation and shared Claude/Pi/DSH workflows carry the requested output language. The [instruction index](instructions.en.md) and [prompt reference](prompt-reference.en.md) provide both reading languages.

The bilingual update passed 56 relevant Python tests, including 63 JavaScript workflow contract scenarios. Tests cover language propagation, unchanged scope and status fields, all five export formats, one Skill entry point, and installer/bootstrap behavior. Local links and ZIP integrity manifests were also checked. Installer `--lang` selects onboarding language only; it does not persist a research-language preference.

An independent agent followed the English Skill with an offline synthetic package: 12 successful CLI commands retained all seven bookmark instances and six unique URLs across four section cards. A copy anchor did not duplicate its underlying bookmarks. The brief, gaps and answer were in English; all five input files were unchanged. With zero retrieval budgets, no fetched pages or claims, the saved research correctly remained incomplete. This is an instruction-use check, not a live webpage or professional-service evaluation.

The bilingual local update was reinstalled and enabled at base version 0.4.0. All shipped files matched the staged export apart from the installation cachebuster. Its actual stdio runtime exposed 35 MCP tools, with SQLite FTS5 available; isolated discovery created no database. Technical diagnostics, original evidence and historical validation records retain their original language.

## Real input and installed runtime

Read-only verification against real user exports produced:

| Input | Bookmark instances | Distinct original URLs | Protocol files |
| --- | ---: | ---: | ---: |
| Research directory export | 223 | 207 | 5 |
| Sample ZIP export | 638 | 557 | 6 |

Changing the research export's directory and reimporting with the same source ID produced zero changed files and zero inserted/updated items. Importing one of its cards preserved all 223 instances. Removing the disposable export copies still allowed queries. Restoring the managed snapshot into a new database reproduced the same counts and input fingerprint. A modification to a separate live copy was indexed without a query. Hashes confirmed that the original directory files and ZIP were unchanged.

The existing personal Codex plugin was updated to 0.4.0 after preserving its previous source directory and taking a consistent SQLite backup. The installed shared runtime matched the repository bytes. Its actual stdio entry exposed **35 tools**, accepted the new source parameters, imported the complete 223-instance package, queried its saved snapshot and listed its history. Runtime/FTS5 checks passed, with no extra output on the MCP stream.

The two previously registered manual exports were migrated to snapshot mode. Their source IDs, item primary keys, item revisions, counts and indexed input fingerprints remained unchanged; neither migration inserted, updated or deleted any bookmark item. A new Codex thread loads the updated Skill and tool catalog.

## Host and provider boundaries

The [host validation evidence](host-validation.json) retains the actual client versions, tool counts and failures observed at each earlier checkpoint.

| Route | Established evidence | Separate acceptance still required |
| --- | --- | --- |
| Codex | Native delegation recipe; preparation script reads all 207 IDs through real stdio MCP; delegated Skill acceptance on a fresh synthetic package produced a correctly incomplete report and two local-evidence Wiki pages | Live webpage research with multiple reader groups and independent child verification |
| Claude Code | 2.1.247 strict plugin validation; live launch loaded the workflow command and connected all 34 MCP tools | Existing configured model endpoint returned 429 / Service Unavailable before any child ran; workflow execution and recovery remain unverified |
| Pi | Project registrar, stdio bridge and isolated extension scenarios | Pi and the two required extensions are not installed in the validation environment |
| DSH | Native call-object generator and isolated workflow scenarios | A configured DSH profile, engine, service and tool are not installed in the validation environment |
| OpenAI / Parallel research APIs | Thin clients and lifecycle/contract tests, separate credentials, secondary report import | No research API credentials were configured; no paid task was submitted |

At the earlier prerelease checkpoint, recorded as 0.3.0 in the original evidence, the personal Codex installation was updated with Codex CLI 0.153.4 after a byte-verified backup. The installed cache exposed all 34 tools over its actual stdio launch command; the CLI FTS5 check and read-only routing/service-description calls passed. All 36 non-manifest export files, including the three Codex host assets, matched the installed bytes. The installation-only cachebuster is separate from the repository version. A new Codex thread is required to load the updated Skill and tools.

Workflow scenarios cover full pagination, independent verifier failures, gap-only follow-up, partial/fatal errors and false completion. The host remains responsible for checking authoritative saved state and artifacts after a workflow returns. These scenarios do not simulate a provider-quality benchmark or prove unavailable clients were run.

An independently delegated Codex agent followed the revised Skill with only the original synthetic canvas input, without reading expected answers or changing code. It preserved seven instances and six URLs, read five local JSON/canvas files, saved six metadata claims, wrote two linked Wiki pages and checked saved state, coverage and hashes. All six URLs use the reserved `.test` domain, so they remained explicitly blocked: accounting was 6/6, original-page text and substantive review were both 0/6, and the investigation remained incomplete. No network or professional research API was called. An additional verifier could not start because the host thread limit was reached; the agent disclosed its own second review rather than claiming independent child verification. The acceptance exposed a report-label issue for local documents, now corrected to show their evidence and content kinds without changing coverage.

The live Claude attempt used an isolated two-URL/three-instance synthetic package with pre-imported text and zero retrieval budget. The first isolated launch did not load user authentication; the second used the existing user model configuration with hooks disabled for that invocation. Both started zero subagents and reported zero usage cost. No global client settings changed. Tool discovery succeeded, but the research run did not; the successful manifest test is not presented as live execution acceptance.

Actual search observations in this implementation session: Exa returned usable search results; Tavily reported `monthly_cap_reached_bonus_eligible` in a structured error envelope despite MCP `isError:false`; Parallel had an SSL EOF transport failure. Error handling now classifies these as provider failures instead of empty successful search. No bonus signup or payment was attempted, and these observations are not permanent claims about service availability.

## Wiki and quality claims

Wiki verification checks accepted, active source claims, immutable revisions, optimistic updates, provenance, changed hashes, crosslinks, Chinese body search and stale-evidence exclusion. Lint reports semantic support as unscored. A semantic review declaration is recorded, not mechanically proven.

The quality verifier uses six explicitly synthetic outputs to exercise answer F1, citation annotations, report rubric scores, four coverage metrics, cost/latency and repeat variance. Unknown labels and measurements remain null. It does not establish quality improvements over ordinary host research or professional services. Real comparisons require actual matched tasks, recorded conditions and independent judgments; see [Wiki and evaluation](wiki-quality.md).

## Limits and distribution

The monitor uses periodic file checks, not native OS file events or a system daemon. Defaults are a 1-second poll, 2-second debounce and 5-second deletion grace; these are scheduling settings, not guaranteed update latency. It does not perform Git authentication or synchronization. Stable-file checks and Git locks cannot make an external exporter atomic. A complete mirror must have valid, agreeing references before its update can be committed.

Snapshots are retained without automatic garbage collection. Local index freshness does not establish that remote webpages are current. Professional API access and full model-driven runs in all four hosts have not been newly validated by this version; the host and provider boundaries above retain those observations.

```sh
python3 scripts/build_zip.py --output dist/bookmark-research-0.4.0.zip
python3 scripts/build_zip.py --include-tests --output dist/bookmark-research-test-pack-0.4.0.zip
```

Each distribution has an internal `MANIFEST.sha256`. User exports, source snapshots, databases, research artifacts, credentials and local validation directories are excluded. GitHub publication is separate from the completed local installation and validation.

Each ZIP has a `MANIFEST.sha256`. Exports carry the shared runtime, Skill and the host-specific adapter; they exclude source packages, user settings, databases and credentials. Git installation remains independent of GitHub Releases. Host loading and optional service authentication follow their real interfaces, not the archive format.

The historical 0.2.0 source-audit JSON contains original bookmark instance mappings, so it is excluded from both 0.4.0 ZIPs. Historical method documents link to that release's repository snapshot instead. The production package contains no synthetic test fixtures; the explicitly requested developer test pack adds only curated tests and synthetic fixtures.

Installer checks require the Codex delegation recipe, preparation script and shared stdio bridge. Local installation and updates compare these assets with the selected source; standalone verification also rejects missing or symlinked host assets. Native Codex tests verify that changed assets reach the updated cache. These are installation integrity checks, not model-driven workflow acceptance.
