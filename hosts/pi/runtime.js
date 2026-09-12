// pi-subagents-workflows injects args/cwd; pi-subagents owns runs and lifecycle.
const host = {
  name: "pi",
  all(jobs) {
    return runs.all(jobs.map(job => ({
      key: job.key, agent: "delegate", task: job.prompt, cwd,
      context: "fresh", outputSchema: job.schema,
    }))).then(values => jobs.map((job, index) => {
      const run = values[index];
      const ok = Boolean(run && !run.error && run.ok !== false && run.structuredOutput);
      return {
        key: job.key, ok, data: ok ? run.structuredOutput : null,
        error: ok ? null : String(run?.error || "Missing structuredOutput or failed child"),
        child_run_id: run?.runId || null,
      };
    }));
  },
};
