# Host Config Layer — Persistent Pass-Through Between Sealed Bundle and Per-Turn Argv

**Status:** DRAFT — pending review.
**Author:** Manoj Prabhakar Paidiparthy
**Date drafted:** 2026-06-01
**Revised:** 2026-06-01 (D3 format changed from YAML to JSON; downstream sections updated accordingly)
**Supersedes / amends:** Mode A amendment (`docs/designs/2026-05-24-aaa-v2-mode-a-pivot-amendment.md`) §3 — specifically removes argv flags `--env-allowlist`, `--env-extra`, `--allow-protocol-skew`; drops env var `AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW`; adds the `--config` resolution and the host-config schema. Mode A's locked decisions D1, D3, D4, D6, D9, D12 are preserved unchanged.
**Audience:** amplifier-agent contributors; host adapter authors (NC, future PC, OpenCode, Claude Code); operators debugging config at runtime.

---

## 1. Problem framing

The Mode A amendment locked a per-turn argv surface that assumes the host re-passes every config knob — `--mcp-servers`, `--host-capabilities`, `--env-allowlist`, `--env-extra`, `--provider`, `--cwd` — on every `amplifier-agent run` invocation. The framing was: "argv is text-first and inspectable; caller is source of truth on every turn." Reasonable for the wire, but it conflated two ideas: (a) the engine stays stateless per turn, and (b) every knob must be re-passed per turn. (a) is an invariant. (b) is a consequence that doesn't follow.

Empirical observation: hosts configure once at install or container-bake time. They do not change MCP server lists between turns. They do not toggle the provider between turns. The Mode A surface forces them to re-serialize the same JSON every invocation anyway. Three gaps result:

1. **Human direct invocation must retype argv every turn.** `amplifier-agent run "..."` at a terminal has no defaults beyond what `bundle.md` hardcoded.
2. **Co-resident hosts on the same machine cannot share or isolate baseline config.** Two hosts driving amplifier-agent on the same box have no agreed surface for "this is my config." They either re-pass argv on every turn or rely on out-of-band coordination.
3. **MCP server config is re-serialized in argv every turn** even though it is stable for the life of the host install. CR-A (the secret-spill tmpfile) makes the spill cheap but does not eliminate the per-turn re-serialization.

All three reduce to one structural absence: there is no persistent config layer between `bundle.md` (sealed at build) and per-turn argv (transient). This design adds that layer.

### Positioning that drives the decision

> *"We provide the mechanism, host decides the policy."* — design owner, 2026-05-30

That sentence rules out amplifier-agent inventing its own config vocabulary, picking a default file location, or curating which knobs each module exposes. It pulls us toward a pass-through: amplifier-agent supplies a resolution mechanism (where the config file lives, when it's read, how unknown keys behave). The schema reflects what downstream modules already expect.

## 2. Assumptions and invariants

**Invariants preserved (not subject to this design):**

- **I1.** Engine stays stateless per turn. Each `amplifier-agent run` is a fresh subprocess; no in-memory state persists across invocations. (Mode A amendment §1.3.)
- **I2.** `bundle.md` stays sealed and vendored. The config layer CANNOT change bundle composition — it can only parameterize what `bundle.md` already declares. Strategy 1 from `docs/designs/2026-05-19-baked-in-bundle-decision.md` is unchanged.
- **I3.** No dependency on amplifier-app-cli's `~/.amplifier/registry.json`. (D6 of the baked-in-bundle decision.)
- **I4.** The wire shape (Mode A §1.2) is unchanged. The envelope, the exit codes, the protocol-version skew check, the secret-spill pattern (CR-A) all stand.
- **I5.** Mid-turn config changes are not supported. The engine reads config once at subprocess startup. Hosts that edit the file mid-session do not see the change until the next turn's subprocess spawns; this is acceptable.

**Assumptions about the caller:**

- **A1.** amplifier-agent is programs-first. Primary callers are host adapters (NC, future PC, OpenCode, Claude Code). The CLI exists so non-Python hosts can spawn amplifier-agent as a subprocess. Direct human invocation is supported but not the primary case.
- **A2.** Containers self-isolate. Two hosts running in separate containers have separate filesystem namespaces; the config-collision question only applies to non-containerized co-residence.
- **A3.** The four supported provider modules are fixed at this revision: `anthropic`, `openai`, `azure-openai`, `ollama`. The provider-config schema is closed against this set.

## 3. Boundaries

**In scope:**

- The `--config <path>` argv flag (already declared but unwired at `src/amplifier_agent_cli/modes/single_turn.py:406`).
- A new `$AMPLIFIER_AGENT_CONFIG` env var.
- The JSON config file schema (four top-level keys).
- Resolution, parsing, validation, and layered merging into the sealed bundle's module configs at bundle-mount time.
- Removal of the three argv flags listed in D10.
- Removal of `AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW` env var handling.
- Removal of `provider_detect.detect_provider()` and its call sites.
- Extension of `amplifier-agent config show` (D8).
- Consolidation of XDG resolution through `persistence.py` (D9).
- A new `default_provider:` field in `bundle.md`.

**Out of scope** (see §10):

- The wire shape, the envelope, the exit codes, the protocol-version handshake.
- Bundle composition. `bundle.md` stays sealed; only parameterization changes.
- Mode B reintroduction.
- Session-state persistence (CR-1). The session path layout (`$XDG_STATE_HOME/amplifier-agent/sessions/<id>/`) is unchanged.
- Cache layout (`$XDG_CACHE_HOME/amplifier-agent/prepared/<key>/`). Unchanged.
- The XDG state and cache directories themselves. Only the config tier loses its XDG default.
- Migration tooling, deprecation windows, rollout coordination. This is a forward-only cleanup; see §8.

## 4. The locked decisions

### D1 — Resolution model: 2-tier, no XDG default

Resolution order. First hit wins.

1. `--config <path>` argv flag.
2. `$AMPLIFIER_AGENT_CONFIG` env var.

Absent both, there is no config tier. `bundle.md` defaults apply. There is no XDG fallback at `$XDG_CONFIG_HOME/amplifier-agent/config.json`.

**Rationale.** A1 makes amplifier-agent programs-first. The XDG default exists in CLI prior art (kubectl, docker, git) to serve a single human at a single `$HOME`. amplifier-agent's primary caller is a program, and multiple programs coexist on one machine. An XDG default in that environment creates silent collision under shared `$HOME` (CI runners with shared UID, co-resident non-containerized hosts). The cases where the XDG default would actually help — the human zero-config case — are also the cases where `bundle.md` defaults are sufficient and a config file is unnecessary. Removing the XDG fallback removes the silent-collision class entirely.

The 2-tier shape preserves the inspectability ordering from Mode A §2.1: an explicit `--config` path shows up in `ps aux`; the env var is one indirection away (visible in the spawning host's environment); there is no third tier to guess at.

### D2 — Hard error on missing or unreadable path

If `--config /path.json` is passed and the file does not exist, cannot be opened, or is not readable, the engine emits a structured error envelope per Mode A §4.1 with `error.code = "config_unreadable"`, `error.classification = "protocol"`, and exits with code 2.

Same behavior if `$AMPLIFIER_AGENT_CONFIG` is set to a path that does not exist or is unreadable. The env var is not silently ignored on missing path — setting it is an affirmative declaration that this file is the config.

**Rationale.** Silent fall-through hides typos (`AMPLIFIER_AGENT_CONFG=/etc/host/aaa.json` would otherwise produce "why aren't my settings applying?" at 2am). Both tiers are explicit; both must succeed if claimed.

### D3 — Format: JSON

The config file format is JSON. The implementation parses it via `json.load`.

**Rationale.** The earlier draft chose YAML on the reasoning that the engine takes the parse cost and that hosts authoring config might want comments or multi-line strings. Reframing on the actual audience inverts that. amplifier-agent is programs-first (A1); the audience writing this file is host adapters and operator tooling, not humans editing YAML in a text editor. Once that frame is correct, JSON wins on five reinforcing dimensions.

First, ecosystem consistency. The Mode A envelope on stdout is JSON. The MCP config file consumed by `tool-mcp` (and threaded via `AMPLIFIER_MCP_CONFIG` per D4) is JSON. The audit files written per turn (Mode A §A2.1') are JSON. The TS and Python wrappers consume the envelope as JSON natively. Switching the host config file to JSON makes the entire amplifier-agent I/O surface a single format. YAML would have been the lone outlier across the whole wire.

Second, the security posture simplifies. `json.load` has no equivalent of `yaml.load`'s arbitrary-code-execution vector — there is no `!!python/object` analogue to defend against, no `safe_load` mandate to enforce, no PyYAML CVE-class concern to track. The implementation rule "MUST use safe_load" disappears entirely; correct usage is the only usage.

Third, the YAML Norway problem disappears. In JSON, `"no"` is unambiguously the string `no`; `false` is unambiguously the boolean; numbers, nulls, and arrays carry their explicit type from the wire. The type coercion ambiguity that motivated the `approval.patterns` string-coercion guard in the earlier D7 is structurally impossible in JSON. D7 simplifies accordingly.

Fourth, the wrappers stay lean. The TS wrapper (`@amplifier/agent-wrapper-ts`) and the Python wrapper currently have no YAML dependency; both speak JSON for the envelope already. Keeping host config in JSON means hosts that programmatically generate config (the common case) reuse the JSON serializer they already have. YAML would have forced a new `js-yaml` dependency into the wrapper repos solely to construct a config file the engine would parse and discard.

Fifth, library extensibility. Hosts that want to build typed config builders, validators, or migration tools can use JSON Schema (well-supported across languages), generate config from any language's standard library, and ship the result without a YAML parser as a transitive dependency. The path to "library on top of the config format" is meaningfully shorter with JSON.

**Tradeoff.** JSON has no native comment syntax. Hosts that want to annotate a config file (e.g., why a particular MCP server is included, why `auto_approve` is on for a CI bot) have two conventions: `_comment` keys that a validator would ignore, or an external `.md` companion file alongside the `.json`. The `_comment`-keys approach collides with D7's strict-unknown-key rule (every `_comment` would need a special case), which would erode the very strictness that catches typos. The recommended pattern is an external companion document — `aaa-config.md` next to `aaa-config.json` — when explanation is needed. Since the design's audience is programs and config is usually host-generated rather than hand-edited, this tradeoff costs little in the common case.

### D4 — Schema: four top-level keys, pass-through to module configs

The config file has four top-level keys. The schema is a **pass-through** to the configs of the modules that `bundle.md` already declares — amplifier-agent does not invent vocabulary, rename keys, or curate which knobs the host can set. The block names match the modules they parameterize.

```json
{
  "mcp": {
    "verbose_servers": false,
    "server_log_dir": "~/.amplifier/logs/mcp-servers/",
    "max_content_size": 50000,
    "configPath": "/etc/host/mcp.json"
  },
  "approval": {
    "patterns": ["rm -rf", "sudo"],
    "auto_approve": false,
    "default_action": "deny",
    "policy_driven_only": false
  },
  "provider": {
    "module": "anthropic",
    "config": {
      "default_model": "claude-sonnet-4-5",
      "max_tokens": 8192
    }
  },
  "allowProtocolSkew": false
}
```

Key-by-key rationale:

| Key | Pass-through target | Notes |
|---|---|---|
| `mcp:` | tool-mcp (`amplifier-module-tool-mcp`) config schema | Matches the module's existing schema verbatim (`verbose_servers`, `server_log_dir`, `max_content_size`). `configPath:` is the one convenience key amplifier-agent adds: when set, the engine sets `AMPLIFIER_MCP_CONFIG` on the subprocess that runs tool-mcp; tool-mcp's own existing 4-tier resolution then consumes it. amplifier-agent does not reinvent path resolution. |
| `approval:` | hooks-approval (`amplifier-module-hooks-approval`) config schema | Matches the module's existing schema verbatim (`patterns`, `auto_approve`, `default_action`, `policy_driven_only`). No new names, no curated subset. |
| `provider:` | The selected provider module's config schema | Shape mirrors the bundle's existing `tools:` entries: `{ module, config }`. `provider.module` is one of the four fixed values (A3). `provider.config:` flows through to whatever module was named; valid keys differ per provider (anthropic has retry tuning and beta headers; openai has prompt-cache and reasoning controls). |
| `allowProtocolSkew:` | engine-level (not a module) | The only top-level key that is not a module pass-through. Suppresses the protocol-version skew check that Mode A §4.4 defines. Was an argv flag and an env var; D10 collapses both into this config key. |

This pass-through stance is the load-bearing decision. It produces one consequence worth naming: amplifier-agent's config schema is coupled to module schemas. If `tool-mcp` adds or renames a config key, amplifier-agent's effective surface changes. This is acceptable because the bundle is sealed — at any given amplifier-agent release, the set of modules and their schemas is known. The alternative (amplifier-agent owning its own vocabulary and translating to modules) is more code, more confusion, and one more place the schemas can drift apart.

### D5 — Layered merge with bundle defaults

When a config block is present, it merges over the bundle's static config for that module. The merge pattern matches the Mode A amendment's tool-mcp threading: `{**bundle_static, **host_overrides}`. Bundle declares the base; host overrides individual keys.

If the host omits a config block, the bundle's value applies. If the host omits a key inside an otherwise-present block, the bundle's value for that key applies. Layering is per-key, not all-or-nothing.

If the host provides no config file at all (D1 absent both tiers), behavior is identical to today: bundle defaults flow unchanged.

### D6 — Bundle gains `default_provider:` field

`bundle.md` must explicitly declare which of the four providers is the default. Provider selection at boot resolves as:

1. `provider.module` from config, if set.
2. Else `default_provider:` from `bundle.md`.
3. (No further fallback. If neither is set in a malformed bundle, the engine hard-errors at boot.)

The existing `provider_detect.detect_provider()` env-var-sniffing path becomes **vestigial** under this design. It conflated two questions — "which provider is configured to run" and "which provider has credentials available" — that this design separates. Config (or bundle) decides which provider runs. The provider module itself raises a loud error at startup if its API key env var is missing. Remove `detect_provider()` and its call sites; the auto-detect warning machinery, the `providerAutoDetected` envelope flag, and the `provider: "auto"` silencer never need to exist.

### D7 — Schema validation: strict-by-default, no escape hatch

- **Malformed JSON** → hard error. `error.code = "config_malformed_json"`, classification `protocol`, exit 2.
- **Unknown top-level keys** (anything outside the four in D4) → hard error. `error.code = "config_unknown_key"`, classification `protocol`, exit 2. There is no `--strict-config` opt-in to soften this; strict IS the default.
- **Top-level key present but no matching module mounted in the bundle** (e.g., the host writes a `notifications` block but the bundle declares no notifications module) → hard error. `error.code = "config_no_matching_module"`, classification `protocol`, exit 2.
- **Value-type mismatch against the schema** (e.g., `provider.module` not a string, `mcp.max_content_size` not an integer, `approval.patterns` containing a non-string list member) → hard error. `error.code = "config_invalid_type"`, classification `protocol`, exit 2. JSON parses produce native types, so the same validation pass that catches `provider.module: 123` also catches `approval.patterns: [123]` or `approval.patterns: [false]` — no language-specific carve-out is needed.
- **Unknown keys INSIDE a pass-through block** (e.g., a key under `mcp` that tool-mcp does not recognize) → module's responsibility. amplifier-agent passes the merged config through; whatever the module does about unknown keys is what happens. amplifier-agent does not intercept.

Validation enforces top-level unknown-key strictness, the module-mount match for each top-level block, and value-type correctness per a JSON Schema (or equivalent runtime check). The previous draft carried a dedicated `approval.patterns` string-coercion guard to defend against the YAML Norway case (`[no]` parsing to `[False]`); D3's switch to JSON makes that carve-out unnecessary — JSON's explicit typing means `"no"` is always the string and `false` is always the boolean, and the generic `config_invalid_type` check covers any type-mismatch case uniformly.

Forward-compatibility (older engine reading newer host's config) is the host's responsibility via `--protocol-version`. Rolling deploys that risk old-engine-new-config skew must coordinate via the version handshake. We accept this at v1 cadence.

### D8 — `amplifier-agent config show` extension

The existing `src/amplifier_agent_lib/admin/config_show.py` (which today reports XDG state, cache, and would-be-config paths and writability) is extended to report:

- **Resolved config path**, or "none" if no tier matched.
- **Resolution source**: one of `--config flag`, `$AMPLIFIER_AGENT_CONFIG env`, `none`.
- **Parsed values** under their pass-through block names, after layered merge with bundle defaults.
- **On parse failure**, the command still prints the resolved path and source so the operator can locate the file before debugging its contents.

This is the 2am debugging affordance. Without it, the combination of two resolution tiers, layered merge, and pass-through to module schemas is too much to reason about by inspection.

### D9 — XDG-utility consolidation (cleanup in scope)

Today three files compute XDG paths independently:

- `src/amplifier_agent_lib/persistence.py:43` (canonical: `state_root()`, `cache_root()`, `config_root()`).
- `src/amplifier_agent_lib/bundle/cache.py:43-51` (private `_xdg_cache_home`).
- `src/amplifier_agent_lib/admin/doctor.py:71-75` (private `_xdg`).

Adding config-read makes the canonical module a fourth call site; not consolidating leaves four duplicates the moment someone adds another XDG lookup. The cleanup is in scope for this design.

`bundle/cache.py` and `admin/doctor.py` must import from `persistence.py` and delete their private helpers. The empty-string env var handling must also be normalized — `persistence.py:28` and `bundle/cache.py:48` currently differ on whether `XDG_CACHE_HOME=""` means "absent" or "explicit empty path"; consolidate on "empty = absent" in `persistence.py`.

### D10 — Argv flags: three dropped, four kept, one wired

Dropped from `amplifier-agent run`:

- `--env-allowlist`. Mode A §3.2 admits the flag exists for diagnostic transparency only; the wrapper builds env itself, the engine does not re-validate. The config file is more inspectable than a flag, and the file is the right place to record host-policy env exposure.
- `--env-extra`. Same reason.
- `--allow-protocol-skew`. Duplicated with the env var `AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW`; both removed. Behavior moves to config key `allowProtocolSkew:`.

Kept (per-invocation by nature):

- `--session-id`.
- `--resume` / `--fresh`.
- `--output` (text or json).
- `--protocol-version` (wrapper-engine handshake; tied to wrapper version, not host policy).

Newly wired:

- `--config <path>`. The stub already exists at `src/amplifier_agent_cli/modes/single_turn.py:406`. This design wires it.

### D11 — What is NOT changed

Explicitly out of scope so the implementation stays focused:

- The wire. Mode A unchanged.
- The envelope schema, except for the removal of the `metadata.hostCapabilities` field tracked in the paired design (`docs/designs/2026-06-01-drop-host-capabilities.md`).
- Bundle composition. Strategy 1 unchanged.
- Mode B is not reintroduced.
- Session-state persistence (CR-1). Unchanged.
- The session-state path layout (`$XDG_STATE_HOME/amplifier-agent/sessions/<id>/`). Unchanged.
- Cache layout (`$XDG_CACHE_HOME/amplifier-agent/prepared/<key>/`). Unchanged.
- The XDG state and cache directories. Only the config tier loses its XDG default.

## 5. Multi-host scenarios

The 2-tier resolution model (D1) is the central design choice for multi-host coexistence. Walk it through:

**Scenario A — Two co-resident programmatic hosts (e.g., NC container + Paperclip container, or NC + Paperclip on the same host without containers).**

Each host sets `$AMPLIFIER_AGENT_CONFIG` in its own process scope at startup. NC's process tree has `AMPLIFIER_AGENT_CONFIG=/etc/nc/aaa.json`; Paperclip's has `AMPLIFIER_AGENT_CONFIG=/etc/paperclip/aaa.json`. Each amplifier-agent subprocess inherits its parent's environment and reads its own file. If hosts run in separate containers, the container boundary additionally isolates filesystem namespaces. If hosts run on the same host without containers, the per-process-tree env scope is sufficient. No collision.

**Scenario B — Parallel CI jobs on a shared runner.**

Each job sets `$AMPLIFIER_AGENT_CONFIG=$JOB_TMP/aaa.json` in its own job environment. With no XDG default, there is no shared `~/.config/amplifier-agent/config.json` for two jobs to contend over. The collision class that would otherwise bite CI most loudly is closed structurally.

**Scenario C — Human direct invocation.**

The operator runs `amplifier-agent run "hello"` with no config file present and no env var set. Both tiers miss; bundle defaults apply. Identical to today's behavior. If the operator wants overrides, they pass `--config /path/to/their/config.json` explicitly per invocation.

**Scenario D — A host wants to share baseline config across instances.**

Each instance sets `$AMPLIFIER_AGENT_CONFIG=/etc/shared/aaa.json`. The "collision" on a single file is intentional sharing, not accidental. amplifier-agent does nothing special; the host expresses the intent by pointing both instances at the same path.

The asymmetry that makes D1 work: hosts that need isolation can express it via the env var (or `--config`); hosts that want sharing can express that too; the case that benefits from a zero-config default (the human) is also the case where bundle defaults are already sufficient. The XDG default served no constituency that the 2-tier model leaves uncovered.

## 6. Risks and what would falsify the design

The catalytic question: **what would have to be true for this design to be wrong?**

- **Hosts develop a need for mid-session config changes.** I5 explicitly defers this. A host that wants per-turn config changes today must pass argv per turn (which the design supports for the four kept flags). If the day comes that hosts want per-turn updates to the four config blocks, the design needs revisiting: either an argv override per turn (re-introducing the surface area we shrank) or a snapshot mechanism (config is snapshotted at session-start and reused for the session's life). Signal: host adapters carrying their own runtime-mutable state on top of the static config file.

- **Pass-through coupling to module schemas becomes painful.** D4 couples amplifier-agent's effective config surface to the schemas of tool-mcp, hooks-approval, and the four provider modules. If those schemas churn faster than amplifier-agent releases, hosts will see "the bundle says one thing, the docs say another" episodes. Signal: module-schema change cadence outpacing amplifier-agent release cadence; bug reports citing module-side config keys that amplifier-agent's docs do not mention.

- **A future host wants two config files merged** (e.g., system + user, or operator + service). This design has one config source per tier and explicitly rejects merging across tiers. If a real use case appears, the resolution model needs a third merge axis. Signal: hosts repeatedly maintaining two-file conventions on top of amplifier-agent and writing their own merge logic.

- **`bundle.md`'s `default_provider:` field becomes a coordination hotspot.** Today `bundle.md` is sealed at release; the field is set once per amplifier-agent release. If hosts want to override the default without overriding the full provider config block, the schema needs an additional layer. Signal: hosts setting `provider.module` in every config file purely to flip the default.

- **The strict-by-default unknown-key policy (D7) gates legitimate rolling deploys.** Hosts that ship a config tailored for amplifier-agent vN+1 cannot run that config against amplifier-agent vN. Today the protocol-version skew check handles this at the wire level; if hosts find themselves managing two config files per amplifier-agent version, the strictness needs softening. Signal: host adapters maintaining a "config for old engine" and "config for new engine" pair.

Each is a monitoring signal, not a current concern. If any becomes true, this design is superseded by another.

## 7. Tradeoffs

Most tradeoffs were resolved in the design conversation that produced this doc. Summary:

| Dimension | Choice | What was sacrificed |
|---|---|---|
| **Resolution model** | 2-tier (flag + env), no XDG default | Zero-config experience for humans who wanted a known file location to edit. Mitigated: bundle defaults serve the human zero-config case. |
| **Format** | JSON | Native comment syntax (mitigated: external companion `.md` when explanation is needed). Gains: ecosystem consistency with the envelope/MCP-config/audit JSON surface; no `safe_load` mandate to enforce; no YAML Norway carve-out in D7; wrappers and host tooling stay free of YAML parser dependencies. |
| **Schema shape** | Pass-through to module configs | Coupling to module schemas. Accepted because bundle is sealed; module set is known per release. |
| **Validation strictness** | Strict-by-default, no escape hatch | Forward compatibility across engine versions. Pushed to the host via `--protocol-version`. |
| **Auto-detect** | Removed (`provider_detect.detect_provider()` deleted) | "Just works without saying which provider." Replaced by `default_provider:` in the bundle. |
| **`allowProtocolSkew` surface** | Config only (env var dropped) | One less ad-hoc override path. Aligns with "host configures once." |

The optimization is for **mechanism purity** (amplifier-agent owns resolution, not policy) and **inspectability** (`amplifier-agent config show` plus `ps aux` plus the env var make the resolution path observable from outside the process).

## 8. Migration scope

This is a forward-only change; there is no existing host config file to migrate. Touch points, in commit-shape order:

1. **Wire the `--config` stub** at `src/amplifier_agent_cli/modes/single_turn.py:406` to read the resolved path, parse with `json.load`, validate per D7, and pass merged values into the bundle-mount step.
2. **Implement the layered merge** (D5) at bundle-mount time. Bundle's static config is the base; the four pass-through blocks override per-key.
3. **Extend `amplifier-agent config show`** per D8.
4. **Refactor `bundle/cache.py` and `admin/doctor.py`** to import XDG helpers from `persistence.py` per D9. Normalize empty-string env handling.
5. **Remove the three dropped argv flags** from `single_turn.py`.
6. **Remove `AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW` handling** from `engine.py:151,163` and `single_turn.py:548,570`.
7. **Remove `provider_detect.detect_provider()`** and its call sites.
8. **Add `default_provider:` to `bundle.md`** (declare `anthropic` as the default — matches today's behavior).

The full task breakdown, test-first sequencing, and per-task acceptance criteria belong to a separate `/write-plan` session that consumes this doc.

## 9. Success metrics

- `amplifier-agent run "..."` with no config file present and no env var set produces behavior identical to today (bundle defaults apply, no warnings).
- A host that ships a 4-section config file gets its overrides applied to the matching modules. `amplifier-agent config show` confirms the resolved path, the resolution source, and the merged values.
- Two co-resident hosts setting different `$AMPLIFIER_AGENT_CONFIG` values produce isolated behavior with no shared filesystem state and no observable interference between their amplifier-agent invocations.
- Adversarial: `provider` block with `"module": "auto"` → hard error at validation. `"auto"` is not one of the four supported modules.
- Adversarial: `"approval": { "patterns": [123] }` (non-string list member) → hard error with `error.code = "config_invalid_type"`, classification `protocol`, exit 2. The same path catches `[false]`, `[null]`, or any other non-string member — JSON's explicit typing means no Norway-style ambiguity is possible.
- Adversarial: top-level `"notifications": { "foo": "bar" }` (unknown key) → hard error with `error.code = "config_unknown_key"`.
- Adversarial: `--config /missing/path.json` → hard error with `error.code = "config_unreadable"`, exit 2. Same for `AMPLIFIER_AGENT_CONFIG=/missing/path.json`.
- Adversarial: a file containing `{ "mcp": { ` (truncated/malformed JSON) → hard error with `error.code = "config_malformed_json"`, exit 2.
- Test suite, ruff, and pyright all clean after the touch-point work in §8.

## 10. What is NOT changed by this design

Out of scope, explicitly listed so the implementation plan does not creep:

- The Mode A wire shape, the envelope schema (except for the paired hostCapabilities removal), the exit codes, the protocol-version handshake.
- Bundle composition. `bundle.md` stays sealed; this design only parameterizes what is declared.
- Mode B is not reintroduced.
- Session-state persistence (CR-1 from Mode A).
- Session and audit path layout under `$XDG_STATE_HOME/amplifier-agent/sessions/<id>/`.
- Cache layout under `$XDG_CACHE_HOME/amplifier-agent/prepared/<key>/`.
- XDG state and cache resolution. Only the **config** tier loses its XDG default; state and cache continue to use XDG conventions through `persistence.py`.
- The CR-A secret-spill tmpfile pattern at `${XDG_RUNTIME_DIR}/amplifier-agent/<sid>/mcp.json`. The config file is non-secret by design; secrets continue to flow through the CR-A path when MCP servers carry API keys.
- Migration tooling. This is a forward-only cleanup; there is no existing host config to migrate from.

## 11. Catalytic question

> **What would have to be true for this design to be wrong?**

Five signals are listed in §6. Each maps to a monitoring concern, not a current defect. The design is acceptable today because:

- amplifier-agent is programs-first; the resolution model is built for that case (A1).
- Module schemas are stable at amplifier-agent release cadence (the bundle is sealed).
- Mid-session config drift is not a requirement today (I5).
- The format is JSON (D3), so type ambiguity (the YAML Norway class of bugs) does not apply, and the strict-validation rules in D7 cover every shape under one uniform `config_invalid_type` path.
- Forward-compat across engine versions is the host's responsibility via `--protocol-version`, not amplifier-agent's via permissive validation.

If any of those premises shift, the design needs revisiting. The signals to watch are named so a future maintainer can recognize the shift before it produces an incident.

---

## Next step

`/write-plan` to produce the implementation plan. The plan should sequence the eight migration items in §8 so that:

- D9 (XDG consolidation) lands first or alongside D1 wiring, so the new config-resolution code path uses the consolidated helper from day one.
- D6 (`default_provider:` in bundle) lands before D7's provider auto-detect removal, so there is no window where neither config nor bundle declares a provider.
- The three argv-flag removals (D10) land together with the config-key additions that subsume them, so no surface is silently duplicated mid-implementation.
