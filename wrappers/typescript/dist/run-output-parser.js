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
/** Maximum stderrTail length retained on synthesized engine errors. */
export const STDERR_TAIL_BYTES = 4096;
/** Maximum stdout snippet included in `envelope_missing` messages. */
const STDOUT_PREVIEW_BYTES = 512;
/**
 * Keep the last `STDERR_TAIL_BYTES` chars of `stderr`.
 * Returns `undefined` for an empty string so callers can omit the field
 * cleanly when there is nothing to surface.
 */
function tailStderr(stderr) {
    if (!stderr)
        return undefined;
    if (stderr.length <= STDERR_TAIL_BYTES)
        return stderr;
    return stderr.slice(stderr.length - STDERR_TAIL_BYTES);
}
const VALID_CLASSIFICATIONS = new Set([
    "transport",
    "protocol",
    "engine",
    "approval",
    "unknown",
]);
/**
 * Validate that `parsed` conforms to the §4.1 envelope shape.
 *
 * Required:
 *   - protocolVersion, sessionId, turnId, reply: string
 *   - error: null | object with `code: string`
 *   - metadata: object
 *
 * Partial / type-wrong envelopes return `false` so the caller falls to Rule 2.
 */
function isShapeValid(parsed) {
    if (parsed === null || typeof parsed !== "object")
        return false;
    const o = parsed;
    if (typeof o.protocolVersion !== "string")
        return false;
    if (typeof o.sessionId !== "string")
        return false;
    if (typeof o.turnId !== "string")
        return false;
    if (typeof o.reply !== "string")
        return false;
    if (typeof o.metadata !== "object" || o.metadata === null)
        return false;
    if (o.error === null)
        return true;
    if (typeof o.error !== "object")
        return false;
    const err = o.error;
    if (typeof err.code !== "string")
        return false;
    return true;
}
/**
 * Parse a subprocess outcome into a single DisplayEvent.
 *
 * See module docstring for precedence rules.
 */
export function parseRunOutput(outcome) {
    const trimmed = outcome.stdout.trim();
    // Attempt to parse stdout as JSON. Failures (empty, partial, non-JSON) are
    // captured silently; the caller falls to Rule 2.
    let parsed = null;
    if (trimmed.length > 0) {
        try {
            parsed = JSON.parse(trimmed);
        }
        catch {
            parsed = null;
        }
    }
    // Rule 1 — envelope parseable per §4.1 → envelope wins.
    if (parsed !== null && isShapeValid(parsed)) {
        const env = parsed;
        if (env.error === null) {
            // Success path — exit code is informational only.
            return { type: "result", text: env.reply };
        }
        // Failure path — populate from the envelope's error fields.
        const err = env.error;
        const classification = err.classification !== undefined &&
            VALID_CLASSIFICATIONS.has(err.classification)
            ? err.classification
            : "unknown";
        const severity = err.severity === "warning" ? "warning" : "error";
        const correlationId = typeof err.correlationId === "string" ? err.correlationId : "";
        const message = typeof err.message === "string" ? err.message : err.code;
        const stderrTail = typeof err.stderrTail === "string" ? err.stderrTail : tailStderr(outcome.stderr);
        return {
            type: "error",
            code: err.code,
            classification,
            severity,
            correlationId,
            message,
            ...(stderrTail !== undefined ? { stderrTail } : {}),
            retryable: false,
        };
    }
    // Rule 2 — envelope absent or unparseable → synthesize from exit + stderr.
    const stderrTail = tailStderr(outcome.stderr);
    if (outcome.exitCode === 0) {
        // Engine protocol violation: exit 0 without a parseable envelope.
        const preview = outcome.stdout.slice(0, STDOUT_PREVIEW_BYTES);
        const previewSuffix = outcome.stdout.length > STDOUT_PREVIEW_BYTES ? "...(truncated)" : "";
        return {
            type: "error",
            code: "envelope_missing",
            classification: "protocol",
            severity: "error",
            correlationId: "",
            message: `Engine exited 0 without emitting a parseable §4.1 envelope. Stdout was: ${JSON.stringify(preview)}${previewSuffix}`,
            ...(stderrTail !== undefined ? { stderrTail } : {}),
            retryable: false,
        };
    }
    // Non-zero exit, envelope absent or partial — engine-class failure.
    return {
        type: "error",
        code: `engine_exit_${outcome.exitCode}`,
        classification: "engine",
        severity: "error",
        correlationId: "",
        message: `Engine exited ${outcome.exitCode} without emitting a parseable §4.1 envelope.`,
        ...(stderrTail !== undefined ? { stderrTail } : {}),
        retryable: false,
    };
}
