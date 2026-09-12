// Contract tests for bundled choreography, not a substitute host installation.
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const scripts = JSON.parse(fs.readFileSync(0, "utf8"));
const ids = Array.from({ length: 207 }, (_, index) => "u-" + index.toString(16).padStart(16, "0"));
let checks = 0;

async function execute(host, scenario = "success", overrides = {}) {
  const calls = [];
  const prompts = [];
  let round = 0;
  const reply = (prompt, schema, key) => {
    calls.push(key);
    prompts.push({ key, prompt, schema });
    assert.equal(schema.type, "object");
    if (key === "inventory") {
      return { status: "ready", research_id: "r-fixture", total: ids.length,
        inventory_ids: scenario === "inventory-drop" ? ids.slice(0, 100) : ids, errors: [] };
    }
    if (key.startsWith("read-") || key.startsWith("verify-")) {
      const group = JSON.parse(prompt.match(/inventory IDs: (\[[^\n]+?\])\./)[1]);
      round = Number(key.split("-")[1]);
      const verify = key.startsWith("verify-");
      const failed = scenario === "source-failure" ? [ids[0]] : [];
      return { status: failed.some(id => group.includes(id)) ? "partial" : "ok", inventory_ids: group,
        reviewed_ids: group.filter(id => !failed.includes(id)),
        verified_ids: verify ? group.filter(id => !failed.includes(id)) : [], blocked_ids: failed.filter(id => group.includes(id)),
        excluded_ids: [], source_ids: ["s1"], claim_ids: ["c1"], errors: failed.length ? ["Source unavailable"] : [] };
    }
    if (key.startsWith("coverage-")) {
      const missing = scenario === "source-failure" ? [ids[0]] : scenario === "difference-drop" ? ids : [];
      const metric = count => ({ count, total: ids.length, rate: count / ids.length });
      return { total: ids.length, inventory_ids: scenario === "coverage-drop" ? ids.slice(1) : ids,
        missing_ids: scenario === "difference-drop" ? missing.slice(0, 100) : missing,
        unread_ids: missing, unreviewed_ids: missing, errors: [], completion_ready: missing.length === 0,
        difference_counts: { missing: missing.length, unread: missing.length, unreviewed: missing.length,
          blocked: missing.length, excluded: 0, reviewed: ids.length - missing.length },
        metrics: { accounted_for: metric(ids.length - missing.length), usable_text: metric(ids.length - missing.length),
          substantive_review: metric(ids.length - missing.length), question_completion: { count: 0, total: 1, rate: 0 } } };
    }
    if (key === "report") {
      const analysis = JSON.parse(prompt.match(/\n(\{"schema_version":1,[^\n]+\})\n/)[1]);
      assert.deepEqual([...analysis.inventory_ids], ids);
      assert.match(prompt, /kind=external_run/);
      assert.match(prompt, /local:fixture-run/);
      const complete = analysis.coverage && !analysis.unverified_ids.length && !analysis.remaining_ids.length;
      return { status: complete || scenario === "false-completion" ? "completed" : "incomplete",
        report_path: "/fixture/report.md", sources_path: "/fixture/sources.json",
        analysis_result_path: scenario === "missing-artifact" ? "" : "/fixture/analysis.json",
        analysis_result_sha256: "0".repeat(64), errors: [] };
    }
    throw new Error("Unexpected child: " + key);
  };
  const shouldFail = key => key === "verify-0-0" && ["child-error", "recover", "false-completion"].includes(scenario);
  const agent = async (prompt, options) => {
    if (scenario === "fatal" && options.label.startsWith("read-")) {
      throw Object.assign(new Error("Host schema/cap failure"), { fatal: true });
    }
    if (shouldFail(options.label)) { calls.push(options.label); return null; }
    return reply(prompt, options.schema, options.label);
  };
  const pipeline = async (items, stage) => Promise.all(items.map(async item => {
    try { return await stage(item); } catch (error) { if (error.fatal) throw error; return null; }
  }));
  const runs = { all: async jobs => {
    if (scenario === "fatal" && jobs[0].key.startsWith("read-")) throw new Error("Host schema/cap failure");
    return jobs.map(job => {
      assert.equal(job.context, "fresh");
      assert.equal(job.agent, "delegate");
      assert(job.outputSchema);
      assert.equal(job.schema, undefined);
      const result = reply(job.task, job.outputSchema, job.key);
      return { ok: true, error: shouldFail(job.key) ? "Fixture child error" : null,
        structuredOutput: result, output: "DO NOT PARSE THIS TEXT", runId: "fixture-" + job.key };
    });
  } };
  const code = scripts[host].replace(/^export const meta = [\s\S]*?;\n\n/, "");
  const context = { args: { research_id: "r-fixture", run_key: "fixture-run", max_gap_rounds: scenario === "recover" ? 1 : 0, ...overrides },
    agent, pipeline, runs, cwd: "/fixture" };
  const result = await new vm.Script("(async () => {\n" + code + "\n})()").runInNewContext(context);
  return { result, calls, round, prompts };
}

(async () => {
  for (const host of ["claude", "dsh", "pi"]) {
    const success = await execute(host);
    assert.equal(success.result.status, "completed");
    assert.equal(success.result.output_language, "auto");
    assert.deepEqual([...success.result.inventory_ids], ids);
    const firstVerify = success.calls.findIndex(key => key.startsWith("verify-"));
    const lastRead = success.calls.map((key, i) => key.startsWith("read-") ? i : -1).reduce((a, b) => Math.max(a, b));
    assert(firstVerify > lastRead, "Independent verification waits for the full reading phase");
    const assigned = success.result.attempts.filter(row => row.phase === "reading").flatMap(row => [...row.inventory_ids]);
    assert.deepEqual([...assigned], ids);
    checks += 1;
    for (const language of ["en", "zh", "fr-CA"]) {
      const localized = await execute(host, "success", { output_language: language });
      assert.equal(localized.result.output_language, language);
      assert.deepEqual([...localized.result.inventory_ids], ids);
      assert.deepEqual(localized.calls, success.calls, "Language must not change workflow phases or scope");
      for (const [index, child] of localized.prompts.entries()) {
        assert(child.prompt.includes(JSON.stringify(language)), "Every child receives the requested language");
        assert.deepEqual(JSON.parse(JSON.stringify(child.schema)), JSON.parse(JSON.stringify(success.prompts[index].schema)),
          "Output language must not translate structured fields or status enums");
      }
      checks += 1;
    }
    for (const invalid of ["", "   ", {}, 42, "en\nzh", "x".repeat(81)]) {
      await assert.rejects(execute(host, "success", { output_language: invalid }), /output_language/);
      checks += 1;
    }
    const dropped = await execute(host, "inventory-drop");
    assert.equal(dropped.result.status, "blocked");
    assert.deepEqual(dropped.calls, ["inventory"]);
    checks += 1;
    for (const scenario of ["coverage-drop", "difference-drop", "source-failure", "child-error"]) {
      const failed = await execute(host, scenario);
      assert.equal(failed.result.status, "incomplete");
      assert.equal(failed.result.inventory_ids.length, 207);
      if (scenario === "child-error") {
        assert(failed.result.unverified_ids.length > 0);
        assert(failed.result.attempts.some(row => row.phase === "verification" && !row.ok));
      }
      checks += 1;
    }
    const recovered = await execute(host, "recover");
    assert.equal(recovered.result.status, "completed");
    assert.equal(recovered.result.unverified_ids.length, 0);
    const extra = recovered.result.attempts.filter(row => row.phase === "reading" && row.round === 1);
    assert.equal(extra.length, 1, "Only the failed group's difference is reread");
    assert.equal(extra[0].inventory_ids.length, 12);
    checks += 1;
    assert.equal((await execute(host, "false-completion")).result.status, "blocked");
    assert.equal((await execute(host, "missing-artifact")).result.status, "blocked");
    checks += 2;
    await assert.rejects(execute(host, "fatal"), /Host schema\/cap failure/);
    await assert.rejects(execute(host, "success", { group_size: 0 }), /group_size/);
    await assert.rejects(execute(host, "success", { run_key: "bad:key" }), /run_key/);
    checks += 3;
  }
  console.log(JSON.stringify({ checks, hosts: ["claude", "dsh", "pi"],
    kind: "isolated script and contract tests; no host or model execution" }));
})().catch(error => { console.error(error); process.exitCode = 1; });
