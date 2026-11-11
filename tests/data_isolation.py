"""Keep test modules out of the user's real Bookmark Research data directory.

Code under test falls back to ``Settings.data_directory()`` for research
registries, default Wiki stores, fetch caches and the CLI index. Import
``setUpModule``/``tearDownModule`` from here in any module that can reach
those defaults, so a full test run never writes into the user's data.
"""

import os
import shutil
import tempfile
from unittest import mock

_ACTIVE = []


def setUpModule():
    root = tempfile.mkdtemp(prefix="bookmark-research-test-data-")
    patch = mock.patch.dict(os.environ, {"BOOKMARK_RESEARCH_DATA_DIR": root})
    patch.start()
    _ACTIVE.append((patch, root))


def tearDownModule():
    while _ACTIVE:
        patch, root = _ACTIVE.pop()
        patch.stop()
        shutil.rmtree(root, ignore_errors=True)
