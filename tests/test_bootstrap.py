"""The GitHub bootstrap delegates every host to the npm command."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which('bash')


@unittest.skipUnless(BASH, 'Bash is required')
@unittest.skipIf(os.name == 'nt', 'Windows uses the npm command directly')
class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='bookmark-bootstrap-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        (self.bin / 'cat').symlink_to(shutil.which('cat'))
        npx = self.bin / 'npx'
        npx.write_text('#!' + sys.executable + '\n' + '''
import json, os, sys
from pathlib import Path
Path(os.environ['BOOTSTRAP_CALLS']).write_text(json.dumps(sys.argv[1:]))
sys.exit(int(os.environ.get('BOOTSTRAP_EXIT', '0')))
''')
        npx.chmod(0o755)
        self.calls = self.base / 'calls.json'
        self.environment = dict(os.environ, PATH=str(self.bin), BOOTSTRAP_CALLS=str(self.calls), LC_ALL='C')
        self.environment.pop('BOOKMARK_RESEARCH_INSTALL_LANG', None)

    def run_script(self, *arguments):
        return subprocess.run([BASH, '-s', '--', *arguments], input=(ROOT / 'install.sh').read_text(),
                              cwd=self.base, env=self.environment, text=True, capture_output=True, timeout=10)

    def test_every_host_uses_the_same_npm_release_without_git(self):
        for host in ('codex', 'claude', 'pi', 'dsh'):
            with self.subTest(host=host):
                args = ['install', '--host', host, '--non-interactive', '--project', '中文 path $(literal)']
                self.assertEqual(self.run_script(*args).returncode, 0)
                self.assertEqual(json.loads(self.calls.read_text()), [
                    '--yes', '--registry=https://registry.npmjs.org', '--package=bookmark-research@latest',
                    'bookmark-research', *args])

    def test_default_action_and_update_verify_are_forwarded(self):
        for args, expected in (((), ['install']), (('--dry-run',), ['install', '--dry-run']),
                               (('update', '--host', 'pi'), ['update', '--host', 'pi']),
                               (('verify',), ['verify'])):
            self.assertEqual(self.run_script(*args).returncode, 0)
            self.assertEqual(json.loads(self.calls.read_text())[4:], expected)

    def test_offline_help_and_language(self):
        self.assertIn('Installer language', self.run_script('--help').stdout)
        self.assertIn('安装器语言', self.run_script('--help', '--lang', 'zh').stdout)
        self.assertIn('npm', self.run_script('--lang=en', '--help').stdout)
        self.assertFalse(self.calls.exists())

    def test_native_or_npm_failure_is_not_masked(self):
        self.environment['BOOTSTRAP_EXIT'] = '17'
        self.assertEqual(self.run_script('install', '--host', 'claude').returncode, 17)

    def test_missing_npx_explains_prerequisite(self):
        (self.bin / 'npx').unlink()
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Node.js/npm', result.stderr)
        self.assertFalse(self.calls.exists())


if __name__ == '__main__':
    unittest.main()
