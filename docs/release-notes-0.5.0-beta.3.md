# Bookmark Research 0.5.0 beta 3

**Beta.** Please report problems on [GitHub Issues](https://github.com/Browser-bookmark-hub/Bookmark-Research/issues).

## Install or update

```sh
npx bookmark-research@latest install   # interactive; macOS, Linux, Windows
bookmark-research update               # if already installed
bookmark-research setup                # choose where research goes and the Wiki follow-up
```

## Changes

- **Research output location** (`output.mode`): `central` (default, path configurable) or `beside_input`, which puts task folders next to the bookmark file or folder (`card.bookmark-research/`, never inside the original). Falls back to central for URL lists, multiple sources, git work trees, canvas packages and unwritable locations, and reports why. `research_start` also accepts a one-off `output_directory`.
- **No migration**: changing the setting affects new tasks only. A location registry keeps every task listed; deleted folders show as `missing`.
- **`work/` folder** per task for the agent's intermediate files, returned by `research_start`.
- **`search_archive`** (new MCP tool and `search-archive` CLI): literal full-text search over archived pages and all research evidence, merged by content hash; Chinese supported. The knowledge archive now stores identical page bodies once.
- **Wiki catalog**: each write regenerates `wiki/index.md` and appends to `wiki/log.md`.
- **Wiki follow-up** (`wiki.after_research`): after `research_finish`, suggest pages and ask first (default), write automatically, or off.
- **Setup and status**: two new setup questions; `status` shows storage locations and recent tasks. README adds a "Where data is stored" table.
- **Cross-platform**: evidence paths are stored with `/`, so task folders move between Windows, macOS and Linux.

## Validation

482 regression tests pass in GitHub Actions on Ubuntu, macOS and Windows with Python 3.9 and 3.12. An isolated end-to-end run checked central, beside-input (folder, ZIP, single file), every fallback, explicit directories, listing after a directory change, Chinese `search_archive` and the Wiki catalog. Pi and real Windows client installs remain untested.

Assets: plugin ZIP, developer test pack and `SHA256SUMS`.
