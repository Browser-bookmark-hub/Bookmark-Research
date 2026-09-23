import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

export const name = "bookmark-research";
export const inject = ["skills"];

// The module travels with the Python runtime; no exporting machine's path is embedded.
const root = fileURLToPath(new URL("../../", import.meta.url));
const skillUrl = new URL("../../skills/bookmark-research/SKILL.md", import.meta.url);
const resourceBase = { kind: "directory", path: fileURLToPath(new URL("./", skillUrl)) };
const candidate = {
  name,
  description: "Research bookmark URLs or Bookmark Canvas packages with shared Python tools and retained evidence.",
  invocation: { modelInvocable: true, userInvocable: true },
  provider: name,
  source: "bundled",
  resourceBase,
  path: fileURLToPath(skillUrl),
  rank: 600,
  locator: skillUrl,
};

export function apply(ctx) {
  ctx.provide("bookmarkResearchPaths", {
    root,
    cli: fileURLToPath(new URL("../../src/cli.py", import.meta.url)),
  });
  ctx.skills.registerProvider(() => ({
    name,
    async list() { return [candidate]; },
    async get() {
      const content = (await readFile(skillUrl, "utf8")).replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, "");
      return { ...candidate, content };
    },
  }));
}
