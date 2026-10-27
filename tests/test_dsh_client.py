"""DSH client discovery across packaged Desktop, PATH, and explicit carriers."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import dsh_client


class DshClientTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bookmark-dsh-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.execute_flags = {}
        if sys.platform == "win32":
            # These fixtures model Darwin carriers, including extensionless
            # scripts and POSIX execute bits, even on the Windows CI runner.
            def posix_which(binary, path=None):
                for directory in (path or "").split(os.pathsep):
                    candidate = Path(directory) / binary
                    if candidate.is_file() and self.execute_flags.get(str(candidate), False):
                        return str(candidate)
                return None
            for patcher in (
                mock.patch.object(dsh_client.shutil, "which", side_effect=posix_which),
                mock.patch.object(dsh_client.os, "access", side_effect=lambda path, mode:
                                  self.execute_flags.get(str(path), False)),
            ):
                patcher.start()
                self.addCleanup(patcher.stop)
        # Discovery must not depend on whether this machine has the app.
        self.layouts = dsh_client.desktop_candidates
        self.discover()

    def discover(self, *paths):
        """Point Desktop discovery at given CLIs, empty by default."""
        patcher = mock.patch.object(dsh_client, "desktop_candidates", lambda *arguments, **keywords: list(paths))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tool(self, name, directory=None, executable=True):
        path = (directory or self.bin) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755 if executable else 0o644)
        self.execute_flags[str(path)] = executable
        return path

    def environment(self, pnpm=False, **values):
        """A hermetic PATH; the POSIX execute bit, not the shell, is what matters."""
        if pnpm:
            self.tool("pnpm")
        environment = {"PATH": str(self.bin), "HOME": str(self.base / "home"), "PATHEXT": ".COM;.EXE;.BAT;.CMD"}
        environment.update(values)
        return environment

    def desktop(self, layout="pnpm"):
        """A DeepSeek Harness Desktop install with a bundled CLI and pnpm copy."""
        runtime = self.base / "Applications" / "DeepSeek Harness.app" / "Contents" / "Resources" / "runtime"
        cli = self.tool("dsh", runtime / "cli" / "bin")
        if layout == "pnpm":
            self.tool("pnpm.mjs", runtime / "pnpm" / "bin", executable=False)
        elif layout == "primary":
            self.tool("pnpm.mjs", runtime / "primary-runtime" / "dependencies" / "pnpm" / "bin", executable=False)
        self.discover(cli)
        return cli

    def test_explicit_missing_path_is_reported_not_substituted(self):
        self.desktop()
        found = dsh_client.resolve(str(self.base / "missing"), self.environment(), "darwin")
        self.assertIsNone(found["binary"])
        self.assertEqual((found["source"], found["reason"], found["usable"]), ("argument", "missing", False))

    def test_path_cli_with_pnpm_is_preferred(self):
        cli = self.tool("dsh")
        self.desktop()
        found = dsh_client.resolve("dsh", self.environment(pnpm=True), "darwin")
        self.assertEqual((found["binary"], found["source"], found["usable"]), (str(cli), "path", True))

    def test_desktop_cli_replaces_a_path_cli_without_pnpm(self):
        self.tool("dsh")
        cli = self.desktop()
        found = dsh_client.resolve("dsh", self.environment(), "darwin")
        self.assertEqual((found["binary"], found["source"], found["usable"]), (str(cli), "desktop", True))
        self.assertTrue(found["bundled_pnpm"].endswith("pnpm.mjs"))

    def test_primary_runtime_pnpm_counts_as_bundled(self):
        self.desktop(layout="primary")
        found = dsh_client.resolve("dsh", self.environment(), "darwin")
        self.assertTrue(found["usable"])
        self.assertEqual(found["source"], "desktop")

    def test_desktop_cli_without_its_pnpm_is_reported_as_unusable(self):
        cli = self.desktop(layout="none")
        found = dsh_client.resolve("dsh", self.environment(), "darwin")
        self.assertEqual((found["binary"], found["source"], found["reason"]), (str(cli), "desktop", "pnpm"))

    def test_path_cli_without_pnpm_and_without_desktop_reports_pnpm(self):
        cli = self.tool("dsh")
        found = dsh_client.resolve("dsh", self.environment(), "darwin")
        self.assertEqual((found["binary"], found["source"], found["reason"]), (str(cli), "path", "pnpm"))

    def test_no_carrier_reports_missing(self):
        found = dsh_client.resolve("dsh", self.environment(), "darwin")
        self.assertEqual((found["binary"], found["source"], found["reason"]), (None, None, "missing"))

    def test_reserved_profile_rejects_a_generic_cli(self):
        cli = self.tool("dsh")
        found = dsh_client.resolve("dsh", self.environment(pnpm=True), "darwin", profile="desktop")
        self.assertEqual((found["binary"], found["source"], found["reason"], found["usable"]),
                         (str(cli), "path", "reserved", False))

    def test_reserved_profile_selects_the_desktop_carrier(self):
        self.tool("dsh")
        cli = self.desktop()
        found = dsh_client.resolve("dsh", self.environment(pnpm=True), "darwin", profile="desktop")
        self.assertEqual((found["binary"], found["source"], found["usable"]), (str(cli), "desktop", True))

    def test_desktop_layouts_follow_each_platform(self):
        darwin = [path.as_posix() for path in self.layouts({"HOME": "/home/user"}, "darwin")]
        self.assertEqual(darwin,
                         ["/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh",
                          "/home/user/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh"])
        windows = [path.as_posix() for path in
                   self.layouts({"LOCALAPPDATA": "/local", "ProgramFiles": "/programs"}, "win32")]
        self.assertEqual(windows, ["/local/Programs/DeepSeek Harness/resources/runtime/cli/bin/dsh.cmd",
                                   "/programs/DeepSeek Harness/resources/runtime/cli/bin/dsh.cmd"])
        self.assertEqual([path.as_posix() for path in self.layouts({}, "linux")],
                         ["/opt/DeepSeek Harness/resources/runtime/cli/bin/dsh",
                          "/usr/lib/deepseek-harness/resources/runtime/cli/bin/dsh"])

    def test_windows_extensionless_full_path_retries_pathext(self):
        cli = self.tool("dsh.cmd")
        environment = self.environment(PATHEXT=".COM;.EXE;.BAT;.CMD")
        self.assertEqual(dsh_client.executable(str(cli)[:-4], environment, "win32"), str(cli))
        self.assertIsNone(dsh_client.executable(str(cli)[:-4], environment, "darwin"))

    def test_non_executable_posix_candidate_is_not_offered(self):
        path = self.tool("dsh", executable=False)
        self.assertIsNone(dsh_client.executable(str(path), self.environment(), "darwin"))

    def profile(self, home, name, dependency=None, enabled=False, manifest=True, bundles=()):
        directory = home / "profiles" / name
        directory.mkdir(parents=True, exist_ok=True)
        if not manifest:
            return directory
        value = {"name": "dsh-profile-" + name, "private": True}
        if dependency:
            value["dependencies"] = {"bookmark-research": dependency}
        if bundles:
            value["dsh"] = {"profile": {"bundles": list(bundles)}}
        (directory / "package.json").write_text(json.dumps(value))
        return directory

    def test_profiles_report_initialized_manifests_and_this_plugin(self):
        home = self.base / "dsh-home"
        self.profile(home, "desktop", dependency="0.5.0-beta.7", enabled=True,
                     bundles=["@deepseek-ai/dsh-base", "bookmark-research"])
        self.profile(home, "web", dependency="link:/somewhere/else")
        self.profile(home, "headless", manifest=False)
        broken = self.profile(home, "broken")
        (broken / "package.json").write_text("{not json")
        # The pnpm store beside the profiles is not a profile.
        (home / "profiles" / "node_modules").mkdir(parents=True)
        (home / "profiles" / "node_modules" / "package.json").write_text("{}")
        rows = {row["name"]: row for row in dsh_client.profiles(home=home)}
        # A directory without a manifest is not an initialized profile.
        self.assertEqual(sorted(rows), ["broken", "desktop", "web"])
        self.assertEqual((rows["desktop"]["initialized"], rows["desktop"]["dependency"], rows["desktop"]["enabled"]),
                         (True, "0.5.0-beta.7", True))
        self.assertEqual((rows["web"]["dependency"], rows["web"]["enabled"]), ("link:/somewhere/else", False))
        self.assertEqual(rows["broken"]["initialized"], False)

    def test_profiles_are_empty_without_a_harness_home(self):
        self.assertEqual(dsh_client.profiles(home=self.base / "absent"), [])


if __name__ == "__main__":
    unittest.main()
