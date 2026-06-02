# Drop `hostCapabilities` from amplifier-agent v1

**Status:** DRAFT — pending review
**Author:** Manoj Prabhakar Paidiparthy
**Date drafted:** 2026-06-01
**Supersedes:** `docs/designs/2026-05-24-aaa-v2-mode-a-pivot-amendment.md` §2.6 D12 (the `host.capabilities` argv flag) and the associated wire/schema/wrapper/test infrastructure.
**Paired with:** `docs/designs/2026-06-01-host-config-layer-revisit.md`. Together these two designs reshape the host-facing surface of amplifier-agent for the v1 host integrations: the config-layer doc adds the durable pass-through surface hosts actually need; this doc removes the write-only inert surface they don't.
**Audience:** amplifier-agent contributors; wrapper maintainers (`amplifier-agent-client-ts`, `amplifier-agent-client-py`); NC adapter maintainers.

---

## 1. Problem framing

The Mode A amendment §2.6 D12 preserved `hostCapabilities` as an argv flag (`--host-capabilities '<json>'`) carrying two booleans — `supports_steering` and `supports_structured_errors` — with the stated rationale that this surface would carry forward-looking capability negotiation for future hosts. A code-grounded audit of the shipped tree surfaces a different reality.

### 1.1 Zero read sites

The field is written but never read for any control-flow decision. Verified locations:

- `src/amplifier_agent_lib/_runtime.py:260` — the *only* assignment site. Writes into `SessionState.metadata["host_capabilities"]` from the parsed CLI argument.
- `src/amplifier_agent_cli/modes/single_turn.py:195`, `:256`, `:299` — echo the value back into the Mode A §4.1 JSON envelope's `metadata.hostCapabilities` field.

Nothing in `src/` branches on the value. No behavior is gated on it. The field is structurally write-only.

### 1.2 Both v1 capabilities turned out to be unneeded

- **`supports_steering`** was specified to gate engine-side steering behavior. Mode A §6 WG-1 deferred all steering work to v1.x and beyond. The B1 buffer mechanism NC actually relies on lives wrapper-side (see the 2026-05-22 NC provider design at line 1225). Steering is host-side, not engine-gated. There is nothing for `supports_steering` to gate in v1, and the v1.x plan does not introduce a gate either.

- **`supports_structured_errors`** was specified to gate whether the engine emits structured errors. Mode A made structured errors the always-on default in the JSON envelope (§4.4). There is no non-structured emission path to fall back to, and no consumer has asked for one. There is nothing for the boolean to gate.

### 1.3 The forward-looking defense protects nothing

The Mode A amendment's R7 defense for keeping the surface was: *"adding a new host requires only an additive boolean field on `HostCapabilities`."* That presupposes the field will be used as the negotiation point for some future capability. With both v1 capabilities resolving to "didn't need engine negotiation," the speculative defense is two-for-two against itself.

The hostCapabilities surface is currently write-only inert infrastructure, defended only by hypothetical future hosts that do not exist. This design removes it.

---

## 2. The locked decision

**D1 — Pure removal across every surface. No engine-side flag tolerance.**

The original removal discussion considered keeping engine flag-tolerance (~3 lines: accept `--host-capabilities`, parse, discard) as a graceful-deprecation buffer for older wrappers. The locked choice rejects this. Removal is pure across engine, wrappers, NC adapter, schemas, fixtures, and tests.

Consequence accepted: any caller pinned to an older wrapper that still emits `--host-capabilities` will hit a click `UsageError`, exit 2, stderr outside the Mode A §4 envelope contract. This is loud rather than silent, and the user directive on this design was explicit: *"don't worry about migration, it should just be cleaned up properly."*

---

## 3. Complete removal inventory

The original Mode A amendment listed only ~6 of the affected files and referenced a fixture filename (`mode-a-host-capabilities.yaml`) that does not exist. The real filename and the broader inventory below came from a code-grounded adversarial review. Cleanup PRs must work from this list, not from the amendment's original count.

### 3.1 Engine (`amplifier-agent`)

- `src/amplifier_agent_cli/modes/single_turn.py:435` — the `--host-capabilities` argv flag declaration and parsing.
- `src/amplifier_agent_lib/_runtime.py:260` — the only assignment site (the session metadata write).
- `src/amplifier_agent_cli/modes/single_turn.py:195`, `:256`, `:299` — the envelope echo paths writing `metadata.hostCapabilities` into the §4.1 envelope.
- `src/amplifier_agent_lib/protocol/methods.py:66` — the `HostCapabilities` TypedDict, plus the `InitializeHostParams.capabilities` reference.

### 3.2 Schemas

- `src/amplifier_agent_lib/protocol/schemas/HostCapabilities.schema.json`
- `src/amplifier_agent_lib/protocol/schemas/InitializeHostParams.schema.json`
- `tests/test_protocol_gen.py:82` — asserts the deleted schema file exists; update to reflect removal.

### 3.3 Wrappers — breaking change

- `wrappers/typescript/src/types.ts:105` — `HostCapabilities` type.
- `wrappers/typescript/src/index.ts:69-70` — `SpawnAgentParams.host` field.
- `wrappers/typescript/test/argv-builder.test.ts` — host-capabilities argv assertions.
- Parity changes in `wrappers/python/src/types.py`, `wrappers/python/src/__init__.py:152`, `wrappers/python/tests/test_argv_builder.py`.
- The argv-builder code in both wrappers that serializes `--host-capabilities` from `params.host`.

This is a backward-incompatible change to the public wrapper API. Any consumer that constructs `SpawnAgentParams` with a `host` field will fail to compile (TS) or raise at runtime (Python).

### 3.4 Conformance fixture

- `src/amplifier_agent_lib/protocol/conformance/fixtures/initialize-with-host-capabilities.yaml` (the actual filename; the Mode A amendment named a non-existent `mode-a-host-capabilities.yaml`).
- All test consumers: `tests/test_phase_2_1_exit_gate.py:52`, `tests/test_protocol_conformance_fixtures.py:105`, `wrappers/conformance/test/runner-ts.test.ts:39`, `wrappers/conformance/tests/test_runner_py.py:48`.

### 3.5 Tests asserting old behavior

- `tests/test_runtime_mcp_threading.py:125` — `test_host_capabilities_stored_in_session_metadata`.
- `tests/cli/test_mode_a_v2_envelope.py:157` — asserts `metadata.hostCapabilities` in the envelope.
- `tests/cli/test_mode_a_audit_trail.py:35` — if it asserts `hostCapabilities` in the audit trail, drop the assertion.

### 3.6 NC adapter (`nanoclaw` repo)

- The `host: { capabilities: { supports_steering: false, supports_structured_errors: true } }` block in NC's adapter `spawnAgent` call, per Mode A §4.1.4.

---

## 4. Notes on lingering state and wire change

Two consequences of removal are worth surfacing explicitly so that a future reader is not surprised.

### 4.1 On-disk lingering state

Old session `metadata.json` files on disk retain an unread `host_capabilities` key, written at `_runtime.py:260` before the removal landed. After this cleanup, new sessions omit the key entirely; old persisted sessions still contain it.

The field is unread either way — this is harmless residue. It is **not** retroactively cleaned. A future reader who finds `host_capabilities` in an old `metadata.json` should treat it as fossil data, not a bug.

### 4.2 Envelope wire change

Removing `metadata.hostCapabilities` from the Mode A §4.1 JSON envelope is a backward-incompatible wire change at protocol 0.x. It is not "pure cleanup" — any consumer that reads the field will see it disappear from the envelope.

Empirically: no consumer reads it today. NC's adapter writes-only; no wrapper or downstream agent inspects the echoed field. Accepted because the protocol is pre-1.0, no consumer is affected, and the surface is dead weight by construction.

The protocol version notes for the release that ships this removal must document the disappearance of `metadata.hostCapabilities` so a future consumer who *would* have started reading it is told up front that the field no longer exists.

---

## 5. Migration scope

The user directive on this design was explicit: *"don't worry about migration, it should just be cleaned up properly."*

This doc therefore states the inventory but does **not** prescribe release ordering across the engine, wrapper, and NC repositories. Whoever implements ships the cleanup; whatever skew window appears between the three repos is loud (click `UsageError`, exit 2 on the engine side; type errors on the wrapper side) and acceptable.

If a future maintainer wants a coordinated lockstep release, they can pick the ordering at implementation time. The design is not constrained by it.

---

## 6. Success metrics

The cleanup is complete when:

- `grep -r "host_capabilities" src/ tests/ wrappers/` returns zero hits (modulo this design doc and any release notes).
- `grep -r "hostCapabilities" wrappers/` returns zero hits.
- The full test suite passes with the §3 inventory deletions applied — no test is left asserting old behavior.
- Invoking `amplifier-agent run` with `--host-capabilities '<json>'` produces a click `UsageError` and exits 2 (the expected loud failure for any caller still pinned to an old wrapper).
- An updated NC adapter that no longer passes `host: { capabilities: ... }` to `spawnAgent` continues to function identically to its pre-removal behavior.

---

## 7. Catalytic question

State the inverse of the decision explicitly: **what would have to be true for keeping `hostCapabilities` to be the right call instead?**

All three conditions must hold within the cost horizon for keeping the surface to be defensible:

1. A second host (Paperclip, OpenCode, Claude Code, or another) actually materializes — not hypothetical, not roadmapped, *shipping*.
2. That host needs engine-side behavior gated on a host-declared capability.
3. That gating genuinely cannot live wrapper-side or host-side.

The empirical track record is the answer to the question. The two v1 capabilities (`supports_steering`, `supports_structured_errors`) both turned out to belong host-side (steering, per the NC provider design) or be unconditional (structured errors, per Mode A §4.4). That is two-for-two against the speculative defense. Removal is the better default; re-adding later is cheap if a real case appears.

### 7.1 Monitoring signal

If a future host PR proposes adding any boolean to a (no-longer-existing) `HostCapabilities` type — or asks the engine to gate behavior on a host-declared property — that is the signal to revisit this decision. Until then, keeping the surface is YAGNI carrying a wire-shape and breaking-change risk for no benefit.
