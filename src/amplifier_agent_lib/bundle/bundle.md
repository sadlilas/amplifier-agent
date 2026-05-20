---
bundle:
  name: amplifier-agent-builtin
  version: 1.0.0
  description: >
    Vendored opinionated manifest for the amplifier-agent CLI (Strategy 1 of
    docs/designs/2026-05-19-baked-in-bundle-decision.md). The manifest text and
    the four sub-session agent definitions are vendored inside this wheel. The
    modules referenced by `source: git+https://...@main` are not vendored — they
    are git-cloned and installed on first invocation. The prepared result is
    cached to $XDG_CACHE_HOME/amplifier-agent/prepared/<aaa_version>/<sha256(bundle.md)>/.
    Editing this file changes the cache key (sha256) and self-invalidates the warm pickle.

session:
  orchestrator:
    module: loop-streaming
    source: git+https://github.com/microsoft/amplifier-module-loop-streaming@main

  context:
    module: context-simple
    source: git+https://github.com/microsoft/amplifier-module-context-simple@main
    config:
      max_tokens: 200000
      compact_threshold: 0.8
      auto_compact: true

  provider:
    module: anthropic-provider
    source: git+https://github.com/microsoft/amplifier-module-anthropic-provider@main

tools:
  - module: tool-todo
    source: git+https://github.com/microsoft/amplifier-module-tool-todo@main
  - module: tool-delegate
    source: git+https://github.com/microsoft/amplifier-foundation@main#subdirectory=modules/tool-delegate

hooks: []

agents:
  include:
    - explorer
    - planner
    - coder
    - tester
---

# amplifier-agent Built-in Bundle (Vendored Opinionated Manifest)

This bundle defines the runtime environment for the **amplifier-agent CLI**. Per
the Strategy 1 decision (`docs/designs/2026-05-19-baked-in-bundle-decision.md`),
only the manifest text and the four sub-session agent definitions (`agents/*.md`
adjacent to this file) are vendored inside the wheel. Module sources are
declared explicitly with `@main` and resolve at runtime via the standard
foundation lazy activator.

## Tool surface at the parent (orchestrator) level

The parent agent loads exactly two tools: `todo` (planning) and `delegate`
(sub-session dispatch). All concrete work — reading files, running commands,
searching, editing — goes through one of the four sub-session agents below,
each of which carries its own tool surface in its frontmatter.

## The four sub-session agents

| Need | Delegate to |
|---|---|
| Understand code, find things, survey docs/configs | `explorer` |
| Design, architecture, code review, write a spec   | `planner`  |
| Implement code from a complete spec               | `coder`    |
| Run tests, measure coverage, generate test cases  | `tester`   |

Agent definitions are vendored in `agents/{explorer,planner,coder,tester}.md`
adjacent to this file. Editing them changes the manifest content hash and
self-invalidates the warm cache.

## Runtime context

The agent runs inside the `amplifier-agent` CLI process. Approval flows and
display updates are mediated by the host adapter — the component that bridges
agent-side events (tool calls, approval requests, stream chunks) to the host
application (e.g. the Paperclip VS Code extension or any compliant JSON-RPC
client).

Session-transcript persistence (writing to
`$XDG_STATE_HOME/amplifier-agent/sessions/<session-id>/`) is **not** owned by
the context module declared above (`context-simple`); it remains a future
CLI-layer hook concern. Out of scope for this manifest.

## Bundle stability

This manifest text is **sealed per release**. Module `source:` URLs use `@main`,
so upstream module updates flow automatically — drift is intentional product
behaviour, not a defect. Editing this file changes the cache key (sha256) and
invalidates all cached prepared bundles. Any change must be intentional and
reviewed as a design decision.
