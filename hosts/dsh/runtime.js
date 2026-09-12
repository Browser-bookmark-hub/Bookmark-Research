// DSH supplies these hooks through its configured workflow engine.
// Fatal hook/schema/cap errors propagate; ordinary child failures remain visible.
const host = {
  name: "dsh",
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
