# User Settings JSON

[中文](configuration.md) · **English**

Bookmark Research keeps its cross-host preferences in its own `settings.json`. Configure them in the terminal wizard during installation, rerun `bookmark-research setup`, or copy and import the [partial JSON example](../config/settings.example.json). The default path is `~/.config/bookmark-research/settings.json`; `BOOKMARK_RESEARCH_CONFIG` or `XDG_CONFIG_HOME` can change it. Multiple hosts can share settings by using the same path.

```sh
bookmark-research config show
bookmark-research config set --input /absolute/path/to/my-settings.json
```

`config set` merges the fields in this partial JSON and keeps settings you did not include. Provider names and choices go in `settings.json`; API keys go in a separate `credentials.json` beside it, or can be entered through the hidden `setup` prompt or supplied as environment variables. Environment variables take precedence. `config set --input` imports preferences only and rejects key fields. `config show` displays effective settings and the config path, never key values.

## What Belongs Here

Use this file for long-term preferences and connection parameters that Bookmark Research reads directly:

- Search and reading sources: `search.providers`, `search.fallback_providers`, `fetch.provider`, `fetch.providers` and concurrency strategies. Perplexity provides structured URL search, not page extraction.
- User preferences: `research.depth`, `research.response_language`, `research.methods`, `archive.enabled`, `wiki.enabled`, `wiki.after_research`, `output.mode`, cache and limit settings, and readiness checks.
- Model endpoints: Base URL, model ID, protocol and search mode under `custom_agentic`. It returns a separate model answer through `agentic_search` and is not fused into `search_web` URL results.
- Professional research APIs called directly by this plugin: the OpenAI Deep Research or Parallel Task API selection under `professional_research`.

`config/settings.example.json` is an importable partial config; remove or change fields to suit your setup. Values must match the current settings schema. Invalid settings are rejected. For defaults, field details and the complete effective settings shape, see the [settings and archives reference](../skills/bookmark-research/references/settings-and-archive.md).

## MCP And Credentials

Do not put every MCP in the plugin's `settings.json`. MCPs launched or authorized directly by the host, such as Exa Agent, Parallel Task and Tavily Research, use host-specific endpoint, command, OAuth and header formats managed by Codex, Claude Code or DSH. The installer/setup can show connection steps, but the plugin JSON does not register host MCPs or store their OAuth credentials.

When Bookmark Research calls a service through its own API, its selection and non-secret connection settings can live here; the key stays separate. For example:

```json
{
  "custom_agentic": {
    "enabled": true,
    "base_url": "https://gateway.example/v1",
    "model": "provider/model-name",
    "api_mode": "responses",
    "search_mode": "native"
  }
}
```

`search_mode: "native"` requests the Responses `web_search` tool and requires upstream support. Chat Completions can only be prompted to search; it cannot guarantee that the upstream will go online. Set the key separately as `CUSTOM_AGENTIC_API_KEY`; never put it in JSON, command-line arguments or chat.

Bookmark Research accepts these API keys for its service adapters. Configure only the keys your selected services need. The setup prompt hides input and saves it for you. You can also maintain the credentials JSON directly:

| Key | Service called by the plugin |
| --- | --- |
| `EXA_API_KEY` | Exa search and page reading |
| `PARALLEL_API_KEY` | Parallel search and page reading |
| `TAVILY_API_KEY` | Tavily fallback search and extraction |
| `JINA_API_KEY` | Jina Search; Reader can fetch anonymously |
| `DEEPSEEK_API_KEY` | DeepSeek Search / Fetch |
| `PERPLEXITY_API_KEY` | Perplexity structured Search |
| `XAI_API_KEY` | Grok `agentic_search` |
| `CUSTOM_AGENTIC_API_KEY` | Custom OpenAI-compatible model endpoint |
| `OPENAI_API_KEY` | OpenAI Deep Research |

```json
{
  "EXA_API_KEY": "your-exa-key",
  "PARALLEL_API_KEY": "your-parallel-key",
  "PERPLEXITY_API_KEY": "your-perplexity-key",
  "CUSTOM_AGENTIC_API_KEY": "your-custom-endpoint-key"
}
```

The default path is `~/.config/bookmark-research/credentials.json`. This is an unencrypted local file and must have mode `0600` (owner-readable only). Use `setup` to save keys so the permissions are set correctly. Set `BOOKMARK_RESEARCH_CREDENTIALS` to change its path. Host-launched MCPs do not read this file; configure their keys through the host's own mechanism.

You can also ask the host to call `update_settings` for a lasting preference or run `bookmark-research config show` to inspect the current config. Installation and update receipts print this guide and the command to reopen setup.
