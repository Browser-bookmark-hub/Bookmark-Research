#!/usr/bin/env node
// Thin cross-platform entry: find Python 3.9+ and run the bundled launcher.
"use strict";
const { spawnSync, spawn } = require("child_process");
const path = require("path");

const launcher = path.join(__dirname, "..", "scripts", "launcher.py");
const candidates = [];
if (process.env.BOOKMARK_RESEARCH_PYTHON) candidates.push([process.env.BOOKMARK_RESEARCH_PYTHON]);
candidates.push(["python3"], ["python"]);
if (process.platform === "win32") candidates.push(["py", "-3"]);

const check = "import sys, sqlite3; sys.exit(0 if sys.version_info >= (3, 9) else 3)";
const python = candidates.find(([command, ...args]) =>
  spawnSync(command, [...args, "-c", check], { stdio: "ignore", windowsHide: true }).status === 0);

if (!python) {
  const chinese = /^zh/i.test(process.env.LC_ALL || process.env.LC_MESSAGES || process.env.LANG || "");
  console.error(chinese
    ? "Bookmark Research 需要 Python 3.9+（含 SQLite）。请从 https://www.python.org/downloads/ 安装，或设置 BOOKMARK_RESEARCH_PYTHON 指向 Python。"
    : "Bookmark Research needs Python 3.9+ with SQLite. Install it from https://www.python.org/downloads/ or set BOOKMARK_RESEARCH_PYTHON.");
  process.exit(1);
}

const [command, ...prefix] = python;
const child = spawn(command, [...prefix, launcher, ...process.argv.slice(2)], { stdio: "inherit", windowsHide: true });
// The terminal delivers Ctrl+C to the whole process group; let Python handle it.
process.on("SIGINT", () => {});
child.on("exit", (code, signal) => process.exit(signal ? 130 : code ?? 1));
child.on("error", (error) => { console.error(error.message); process.exit(1); });
