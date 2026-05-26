/**
 * run-output-parser.ts — parse the Mode A v2 subprocess outcome into a DisplayEvent.
 *
 * Implements §4.1 envelope schema and §4.4 (SC-D) precedence rules from
 * `docs/designs/2026-05-24-aaa-v2-mode-a-pivot-amendment.md`:
 *
 *   Rule 1 — envelope parseable per §4.1 → envelope is authoritative.
 *     The `error` field (null or populated) drives the wrapper's outcome.
 *     The exit code is informational and does NOT override the envelope.
 *
 *   Rule 2 — envelope absent / unparseable / partial → synthesize an error
 *            event from exit code and stderr tail. Partial JSON is NOT
 *            half-parsed (belt-and-suspenders): if any required §4.1 field
 *            is missing, the envelope is treated as unparseable.
 *
 * stderrTail is truncated to STDERR_TAIL_BYTES (4096) on synthesized paths;
 * on the envelope path it is taken verbatim from the engine.
 */
import type { DisplayEvent } from "./session.js";
/** Maximum stderrTail length retained on synthesized engine errors. */
export declare const STDERR_TAIL_BYTES = 4096;
/** Outcome of running the `amplifier-agent run --output json` subprocess. */
export interface SubprocessOutcome {
    stdout: string;
    stderr: string;
    exitCode: number;
}
/**
 * Parse a subprocess outcome into a single DisplayEvent.
 *
 * See module docstring for precedence rules.
 */
export declare function parseRunOutput(outcome: SubprocessOutcome): DisplayEvent;
