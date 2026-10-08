"""Release selectors, safe npm extraction, and persistent installation origins."""

from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import export_bundle
import host_clients
import npm_source


class Registry:
    """Serve real tarballs without a network registry; leave host commands real."""
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.run_original = subprocess.run
        self.error = False
        self.extra = None

    def run(self, args, **kwargs):
        if args[:2] != ['npm', 'pack']:
            return self.run_original(args, **kwargs)
        self.calls.append(args)
        if self.error:
            return subprocess.CompletedProcess(args, 1, '', 'registry unavailable')
        base = Path(args[args.index('--pack-destination') + 1])
        filename = 'bookmark-research.tgz'
        with tarfile.open(base / filename, 'w:gz') as archive:
            archive.add(self.root, arcname='package')
            if self.extra:
                archive.addfile(self.extra, io.BytesIO(b'x') if self.extra.isfile() else None)
        version = export_bundle.read_plugin_manifest(self.root)['version']
        return subprocess.CompletedProcess(args, 0, json.dumps([
            {'name': 'bookmark-research', 'version': version, 'filename': filename}]), '')

    @contextmanager
    def active(self):
        resolve = host_clients.executable
        with mock.patch.object(host_clients, 'executable', side_effect=lambda name: 'npm' if name == 'npm' else resolve(name)), \
                mock.patch('npm_source.subprocess.run', side_effect=self.run):
            yield self


class NpmSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='bookmark-npm-test-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'source'
        export_bundle.export_bundle('codex', self.root)
        self.registry = Registry(self.root)

    def test_sources_accept_latest_or_exact_versions_only(self):
        import install
        import host_install
        for parser in (npm_source.source, install._source, host_install._source):
            self.assertEqual(parser('npm:bookmark-research'), {
                'sourceType': 'npm', 'source': 'bookmark-research', 'ref': 'latest'})
            self.assertEqual(parser('npm:bookmark-research@1.2.3-beta.1')['ref'], '1.2.3-beta.1')
            for invalid in ('npm:other', 'npm:bookmark-research@', 'npm:bookmark-research@^1',
                            'npm:bookmark-research@file:/tmp/source', 'npm:bookmark-research@--flag'):
                with self.subTest(parser=parser.__module__, invalid=invalid), self.assertRaises(ValueError):
                    parser(invalid)
            with self.assertRaises(ValueError):
                parser('npm:bookmark-research', ref='main')

    def test_download_disables_scripts_checks_version_and_cleans_temporary_files(self):
        with self.registry.active(), npm_source.checkout(npm_source.source('npm:bookmark-research'), 20) as (root, version):
            self.assertEqual(version, export_bundle.read_plugin_manifest(self.root)['version'])
            self.assertEqual((root / 'src/cli.py').read_bytes(), (self.root / 'src/cli.py').read_bytes())
            downloaded = root
        self.assertFalse(downloaded.exists())
        self.assertIn('--ignore-scripts', self.registry.calls[0])
        self.assertIn(npm_source.REGISTRY, self.registry.calls[0])
        with self.registry.active(), self.assertRaisesRegex(ValueError, 'version'):
            with npm_source.checkout(npm_source.source('npm:bookmark-research@99.0.0'), 20):
                self.fail('mismatched pin accepted')

    def test_archive_traversal_and_links_are_rejected(self):
        for name, link in (('package/../../escape', None), ('/tmp/escape', None),
                           ('package/link', '/tmp/escape'), ('package/..\\escape', None)):
            member = tarfile.TarInfo(name)
            if link:
                member.type, member.linkname = tarfile.SYMTYPE, link
            else:
                member.size = 1
            self.registry.extra = member
            with self.subTest(name=name), self.registry.active(), self.assertRaisesRegex(ValueError, 'Unsafe entry'):
                with npm_source.checkout(npm_source.source('npm:bookmark-research'), 20):
                    self.fail('unsafe archive accepted')
        self.assertFalse((self.base / 'escape').exists())

    def test_registry_failure_is_reported(self):
        self.registry.error = True
        with self.registry.active(), self.assertRaisesRegex(RuntimeError, 'registry unavailable'):
            with npm_source.checkout(npm_source.source('npm:bookmark-research'), 20):
                self.fail('failed registry accepted')

    @unittest.skipUnless(os.environ.get('BOOKMARK_RESEARCH_TEST_PUBLISHED_NPM') == '1' and shutil.which('npm'),
                         'Published release download requires npm and explicit opt-in')
    def test_real_published_package_supplies_all_four_host_formats(self):
        import host_install
        catalog = json.loads((ROOT / '.agents/plugins/marketplace.json').read_text())
        version = catalog['plugins'][0]['source']['version']
        with npm_source.checkout(npm_source.source('npm:bookmark-research@' + version), 90) as (root, actual):
            self.assertEqual(actual, version)
            self.assertTrue(host_install.runtime_check(root, 30)['fts5'])
            for host in ('codex', 'claude', 'pi', 'dsh'):
                output = self.base / host
                result = export_bundle.export_bundle(host, output, root)
                self.assertEqual(result['version'], version)
                skill = 'skills/bookmark-research/SKILL.md'
                self.assertEqual((output / skill).read_bytes(), (root / skill).read_bytes())
                self.assertFalse((output / '.claude/settings.local.json').exists())


if __name__ == '__main__':
    unittest.main()
