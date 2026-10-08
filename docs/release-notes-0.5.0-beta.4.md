# Bookmark Research 0.5.0 beta 4

**Beta / 测试版.** Published on the npm `beta` channel. The npm `latest` tag is unchanged.

## Install this beta

Pin both the installer and the plugin content so the default `latest` source cannot select an earlier release:

```sh
npx bookmark-research@0.5.0-beta.4 install --source npm:bookmark-research@0.5.0-beta.4
```

Choose Codex, Claude Code, Pi or DSH in the installer, or supply the host explicitly:

```sh
npx bookmark-research@0.5.0-beta.4 install codex --source npm:bookmark-research@0.5.0-beta.4
npx bookmark-research@0.5.0-beta.4 install claude --source npm:bookmark-research@0.5.0-beta.4
npx bookmark-research@0.5.0-beta.4 install pi --source npm:bookmark-research@0.5.0-beta.4
npx bookmark-research@0.5.0-beta.4 install dsh --profile web --source npm:bookmark-research@0.5.0-beta.4
```

Existing installations retain their source and version selection. The GitHub Codex marketplace will point to this npm version after publication; existing managed Git/local or pinned npm installs are not silently migrated.

## Changes

- **One npm release for all four hosts.** The shell bootstrap delegates to the npm launcher. Host adapters generate the required format and use each host's native registration commands. Pi's base installation provides the Skill and CLI; MCP availability follows each host adapter.
- **Durable installation sources.** npm installs retain a managed export and source receipt, so updates do not depend on an expired temporary npx directory. Explicit version pins and existing Git/local origins are preserved.
- **Clean payloads.** npm and Codex's native npm installation exclude personal agent state, development tests and build artifacts. Only the required `.codex-plugin/plugin.json` and `.agents/plugins/marketplace.json` hidden metadata files are included.
- **Actionable Canvas Skill.** The main Skill explains when to query locally, read a known URL, investigate a question or retain a research report. It reads `.canvas` layout before selecting card context, preserves independent text cards, distinguishes directed and undirected edges, and avoids double-counting permanent copy anchors.
- **Large Canvas guidance.** The Skill describes compact local JSON extraction when a whole layout is too large. No graph service, dependency or new MCP tool is added.
- **Release checks.** CI covers Python 3.9/3.12 on Linux, macOS and Windows, native Codex installation/update, all four exported host formats and npm package contents. Release candidates are npm `.tgz` files with SHA-256 checksums.

## Validation and limits

The implementation passed the existing 495-test local suite (one opt-in test skipped) and all 10 CI jobs before this version bump. A local Canvas sample passed 14 comparisons between original JSON and actual MCP responses, including bookmark metadata, geometry, group membership and copy identity; original files remained unchanged. Nine MCP operations were exercised in that sample session.

Web reading was also exercised: one URL failed through all configured fallback readers; another returned a partial excerpt that could be retrieved from the local archive. This release does not guarantee webpage availability, complete extraction, interpretation of unstated user intent or large-canvas performance. End-to-end Skill triggering across every host and every MCP operation is not established by these tests.

The release artifact is the tested npm tarball, also attached here with its checksum. GitHub's automatically generated source archives are source checkouts, not the installation package. Historical ZIP attachments remain available on earlier releases.
