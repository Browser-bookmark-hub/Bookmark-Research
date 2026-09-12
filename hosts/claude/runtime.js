// Claude Dynamic Workflows supplies agent() and pipeline().
const host = {
  name: "claude_code",
  async all(jobs) {
    const values = await pipeline(jobs, job => agent(job.prompt, {
      label: job.key, schema: job.schema,
    }));
    return jobs.map((job, index) => ({
      key: job.key, ok: values[index] != null, data: values[index] ?? null,
      error: values[index] == null ? "Native workflow child failed or returned no result" : null,
    }));
  },
};
