import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

export const name = "bookmark-research";
export const inject = ["skills"];

// The module travels with the Python runtime; no exporting machine's path is embedded.
const root = fileURLToPath(new URL("../../", import.meta.url));
const cli = fileURLToPath(new URL("../../src/cli.py", import.meta.url));
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

// The MCP child inherits only these variables, so saved data/config paths and
// provider keys survive without baking values into a published patch. This list
// must equal the native manifest's mcpServers env_vars; tests assert that parity.
const FORWARDED_ENV = [
  "BOOKMARK_RESEARCH_DATA_DIR",
  "BOOKMARK_RESEARCH_CONFIG",
  "BOOKMARK_RESEARCH_CREDENTIALS",
  "XDG_DATA_HOME",
  "XDG_CONFIG_HOME",
  "EXA_API_KEY",
  "PARALLEL_API_KEY",
  "TAVILY_API_KEY",
  "JINA_API_KEY",
  "OPENAI_API_KEY",
  "SystemRoot",
  "windir",
];

// The same discovery order as the npm launcher: an explicit interpreter, then
// the platform aliases, each accepted only with Python 3.9+ and SQLite present.
const PYTHON_PROBE = "import sys, sqlite3; sys.exit(0 if sys.version_info >= (3, 9) else 3)";

function findPython() {
  const candidates = [];
  if (process.env.BOOKMARK_RESEARCH_PYTHON) candidates.push([process.env.BOOKMARK_RESEARCH_PYTHON]);
  candidates.push(["python3"], ["python"]);
  if (process.platform === "win32") candidates.push(["py", "-3"]);
  for (const [command, ...args] of candidates) {
    const probe = spawnSync(command, [...args, "-c", PYTHON_PROBE], { stdio: "ignore", windowsHide: true });
    if (probe.status === 0) return { command, args };
  }
  return undefined;
}

export function apply(ctx) {
  let python = findPython();
  if (python === undefined) {
    process.stderr.write("bookmark-research: no Python 3.9+ with SQLite was found; the MCP client will try python3. "
      + "Set BOOKMARK_RESEARCH_PYTHON to select an interpreter.\n");
    python = { command: "python3", args: [] };
  }
  // Preflight the files this provider advertises. A stale registration used to
  // surface only as an ENOENT when the host tried to load the Skill or start
  // the MCP child, with nothing telling the user how to recover.
  const missing = [cli, fileURLToPath(skillUrl)].filter((path) => !existsSync(path));
  if (missing.length > 0) {
    process.stderr.write("bookmark-research: installation is incomplete; missing " + missing.join(", ") + ".\n"
      + "Reinstall the plugin (for example: npx --yes --package=bookmark-research@latest bookmark-research install"
      + " --host dsh) or remove the stale registration that points at a deleted install directory.\n");
    return;
  }
  const env = Object.fromEntries(FORWARDED_ENV
    .filter((key) => process.env[key] !== undefined)
    .map((key) => [key, process.env[key]]));
  ctx.provide("bookmarkResearchPaths", {
    root,
    cli,
    python,
    mcpArgs: [...python.args, cli, "serve"],
    env,
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
