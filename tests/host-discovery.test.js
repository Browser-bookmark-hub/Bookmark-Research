// Contract tests for the discovery choreography; no host or model runs here.
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const scripts = JSON.parse(fs.readFileSync(0, "utf8"));
const QUESTION = "How do I run EmbeddingGemma locally?";
const PLAN_URLS = ["https://cards.example/1", "https://cards.example/2", "https://cards.example/3",
  "https://cards.example/4", "https://cards.example/5", "https://cards.example/6",
  "https://cards.example/7", "https://cards.example/8"];
const SEARCH_URLS = ["https://web.example/a", "https://web.example/b"];
const LONG = "Usable page text sentence. ".repeat(20);
let checks = 0;

async function execute(host, scenario = "success", overrides = {}, rawArgs = null) {
  const calls = [];
  const prompts = [];
  const bundles = [];
  const shouldFail = key => key === "bundle-0" && scenario === "bundle-error";
  const reply = (key, schema, prompt) => {
    calls.push(key);
    prompts.push({ key, prompt, schema });
    assert.equal(schema.type, "object");
    if (key === "plan") {
      if (scenario === "plan-error") {
        return { status: "blocked", urls: [], card_labels: [], task_shape: "investigation", route: null,
          errors: ["plan_research failed"] };
      }
      const count = scenario === "empty" ? 0
        : scenario === "second-round" || scenario === "insufficient" ? 3 : PLAN_URLS.length;
      const urls = PLAN_URLS.slice(0, count).map(url => ({ url, title: "Card", instances: 1, source_instances: 1 }));
      return { status: urls.length ? "ready" : "empty", urls, card_labels: urls.length ? ["Card 1"] : [],
        task_shape: "investigation", route: "quick", errors: [] };
    }
    if (key === "search-0") {
      const rows = scenario === "budget-stop" ? [] : SEARCH_URLS.map(url => ({ url, title: "Search result",
        text: "", content_state: "unavailable", published_at: null }));
      return { status: "ok", sources: rows, errors: [] };
    }
    if (key.startsWith("read-")) {
      if (scenario === "read-error" && key === "read-0") {
        return { status: "blocked", sources: [], errors: ["fetch_web failed"] };
      }
      const requested = JSON.parse(prompt.match(/one call: (\[[^\n]*?\]). Return one source/)[1]);
      const rows = requested.map((url, index) => {
        const usable = scenario === "success" ? index < 3 : scenario === "second-round"
          ? (key === "read-0" ? index < 1 : true) : false;
        return { url, title: "Page", text: usable ? LONG : "",
          content_state: usable ? "usable" : "content_insufficient", published_at: null };
      });
      return { status: rows.some(row => row.content_state === "usable") ? "ok" : "partial", sources: rows, errors: [] };
    }
    if (key.startsWith("bundle-")) {
      const payload = prompt.match(
        /\{sources: (\[.*?\]), max_characters: 40000, steps: (\d+), fetches: (\d+), variants: (\d+), elapsed_seconds: (\d+)\}\./);
      assert(payload, "The bundle child receives the counters inline");
      const round = Number(key.split("-")[1]);
      bundles.push({ round, sources: JSON.parse(payload[1]), steps: Number(payload[2]),
        fetches: Number(payload[3]), variants: Number(payload[4]) });
      const verdict = scenario === "success"
        ? { continue: true, reason: null, evidence_count: 3, unavailable_count: 7,
            remaining: { steps: 2, fetches: 0, variants: 2, seconds: 90 } }
        : scenario === "second-round"
          ? (round === 0
            ? { continue: true, reason: null, evidence_count: 1, unavailable_count: 4,
                remaining: { steps: 2, fetches: 5, variants: 2, seconds: 45 } }
            : { continue: false, reason: "steps_reached", evidence_count: 1, unavailable_count: 4,
                remaining: { steps: 0, fetches: 5, variants: 2, seconds: 44 } })
          : scenario === "insufficient"
            ? { continue: true, reason: null, evidence_count: 0, unavailable_count: 5,
                remaining: { steps: 1, fetches: 5, variants: 2, seconds: 10 } }
            : { continue: false, reason: "fetches_reached", evidence_count: 0, unavailable_count: 8,
                remaining: { steps: 2, fetches: 0, variants: 2, seconds: 40 } };
      return { status: "ok", budget: { continue: verdict.continue, reason: verdict.reason,
          used: { steps: bundles[bundles.length - 1].steps, fetches: bundles[bundles.length - 1].fetches,
            variants: bundles[bundles.length - 1].variants, seconds: 40 },
          remaining: verdict.remaining },
        evidence_count: verdict.evidence_count, unavailable_count: verdict.unavailable_count,
        degradation: "excerpts",
        bundle: JSON.stringify({ evidence_count: verdict.evidence_count,
          gaps: verdict.evidence_count ? [] : ["No usable page text was collected for this question"] }),
        errors: [] };
    }
    throw new Error("Unexpected child: " + key);
  };
  const agent = async (prompt, options) =>
    shouldFail(options.label) ? null : reply(options.label, options.schema, prompt);
  const pipeline = async (items, stage) => Promise.all(items.map(item => stage(item)));
  const runs = { all: async jobs => jobs.map(job => {
    assert.equal(job.context, "fresh");
    assert.equal(job.agent, "delegate");
    assert(job.outputSchema);
    assert.equal(job.schema, undefined);
    const failed = shouldFail(job.key);
    return { ok: !failed, error: failed ? "Fixture bundle failure" : null,
      structuredOutput: failed ? null : reply(job.key, job.outputSchema, job.task), runId: "fixture-" + job.key };
  }) };
  const code = scripts[host].replace(/^export const meta = [\s\S]*?;\n\n/, "");
  const context = { args: rawArgs ?? { question: QUESTION, source_id: "host-fixture", run_key: "fixture-run", ...overrides },
    agent, pipeline, runs, cwd: "/fixture" };
  const result = await new vm.Script("(async () => {\n" + code + "\n})()").runInNewContext(context);
  return { result, calls, prompts, bundles };
}

(async () => {
  for (const host of ["claude", "dsh", "pi"]) {
    const success = await execute(host);
    assert.equal(success.result.status, "ok");
    assert.equal(success.result.host_stop, "evidence_satisfied");
    assert.equal(success.result.route, "quick");
    assert.equal(success.result.task_shape, "investigation");
    assert.deepEqual([...success.result.cards], ["Card 1"]);
    assert.equal(success.result.evidence_count, 3);
    assert.equal(JSON.parse(success.result.bundle).evidence_count, 3);
    assert.deepEqual(success.calls, ["plan", "read-0", "search-0", "bundle-0"]);
    assert.deepEqual(success.bundles.map(row => [row.steps, row.fetches, row.variants]), [[4, 8, 1]]);
    for (const child of success.prompts) {
      assert(child.prompt.includes(QUESTION) && child.prompt.includes("host-fixture"),
        "Every child carries the question and the source");
    }
    checks += 1;
    const second = await execute(host, "second-round");
    assert.equal(second.result.status, "partial");
    assert.equal(second.result.host_stop, "budget");
    assert.deepEqual(second.calls, ["plan", "read-0", "search-0", "bundle-0", "read-1", "bundle-1"]);
    assert.deepEqual(second.bundles.map(row => [row.steps, row.fetches, row.variants]), [[4, 3, 1], [6, 5, 1]]);
    const reread = second.prompts.find(child => child.key === "read-1");
    assert(reread.prompt.includes(SEARCH_URLS[0]) && reread.prompt.includes(SEARCH_URLS[1]),
      "URLs discovered by the search are read in the next round");
    assert.equal(second.bundles[1].sources
      .filter(row => row.url.startsWith("https://web.example/") && row.content_state === "usable").length, 2,
      "The usable reread replaces each unread placeholder");
    assert.equal(second.bundles[1].sources.length, 5, "One row per URL reaches the bundle");
    checks += 1;
    const stopped = await execute(host, "budget-stop");
    assert.equal(stopped.result.status, "no_evidence");
    assert.equal(stopped.result.host_stop, "budget");
    assert.equal(stopped.result.budget.continue, false);
    assert.equal(stopped.result.budget.reason, "fetches_reached");
    assert.deepEqual(stopped.calls, ["plan", "read-0", "search-0", "bundle-0"]);
    checks += 1;
    const insufficient = await execute(host, "insufficient", { max_steps: 5 });
    assert.equal(insufficient.result.host_stop, "insufficient_remaining_budget");
    assert(!insufficient.calls.includes("read-1"), "No round starts without budget for its read and bundle");
    checks += 1;
    const empty = await execute(host, "empty");
    assert.equal(empty.result.status, "empty");
    assert.equal(empty.result.host_stop, "plan_empty");
    assert.deepEqual(empty.calls, ["plan"]);
    assert.match(empty.result.next_action, /do not widen/);
    checks += 1;
    const planError = await execute(host, "plan-error");
    assert.equal(planError.result.status, "blocked");
    assert.equal(planError.result.host_stop, "plan_blocked");
    assert.deepEqual([...planError.result.errors], ["plan_research failed"]);
    assert.deepEqual(planError.calls, ["plan"]);
    checks += 1;
    const readError = await execute(host, "read-error");
    assert.equal(readError.result.status, "no_evidence");
    assert.deepEqual([...readError.result.errors], ["fetch_web failed"]);
    checks += 1;
    const bundleError = await execute(host, "bundle-error");
    assert.equal(bundleError.result.status, "blocked");
    assert.equal(bundleError.result.host_stop, "bundle_error");
    assert.equal(bundleError.result.errors.length, 1);
    checks += 1;
    const bridge = await execute(host, "success", { bridge_path: "/bundle/hosts/shared/research-call.py" });
    assert.deepEqual(bridge.calls, success.calls);
    for (const child of bridge.prompts) assert(child.prompt.includes('"/bundle/hosts/shared/research-call.py"'));
    checks += 1;
    const localized = await execute(host, "success", { output_language: "zh" });
    assert.deepEqual(localized.calls, success.calls);
    for (const child of localized.prompts) assert(child.prompt.includes('"zh"'));
    for (const [index, child] of localized.prompts.entries()) {
      assert.deepEqual(JSON.parse(JSON.stringify(child.schema)), JSON.parse(JSON.stringify(success.prompts[index].schema)),
        "Output language must not translate structured fields");
    }
    checks += 1;
    for (const invalid of [{ question: "" }, { question: "x".repeat(2001) }, { source_id: "bad id" },
                           { run_key: "x:y" }, { max_steps: 0 }, { max_steps: 7 }, { max_steps: 2.5 },
                           { output_language: "  " }, { output_language: "x".repeat(81) }]) {
      await assert.rejects(execute(host, "success", invalid), /question|source_id|run_key|max_steps|output_language/);
      checks += 1;
    }
    await assert.rejects(execute(host, "success", {}, 42), /args must be an object/);
    checks += 1;
  }
  console.log(JSON.stringify({ checks, hosts: ["claude", "dsh", "pi"],
    kind: "isolated discovery script and contract tests; no host or model execution" }));
})().catch(error => { console.error(error); process.exitCode = 1; });
