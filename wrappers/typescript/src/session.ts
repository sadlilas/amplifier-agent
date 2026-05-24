/**
 * SessionHandle — one-shot session wrapper.
 *
 * submit(prompt) returns AsyncIterable<DisplayEvent>:
 *   - Sends turn/submit via JSON-RPC
 *   - Yields every display/event-shaped notification that arrives
 *   - Terminates the iterator when result/final notification is observed
 *     OR when the turn/submit JSON-RPC response arrives (whichever first)
 *   - L14 safety net: if turn/submit response contains a non-null reply and
 *     result/final was never observed, synthesizes a result/final DisplayEvent
 *     with synthesized: true as the last yielded event.
 *
 * Per design D10, only one submit() per subprocess lifetime in v1.
 * A second call throws AaaError(lifecycle_unsupported).
 *
 * cancel()/dispose() both call terminate() on the underlying transport (D3).
 */

// TODO(phase-b-task-8): delete unused L14 imports after subprocess driver lands
import { synthesizeFinalIfMissing } from "./l14.js";
import { makeApprovalHandler } from "./approval.js";
import type { ApprovalAdapter } from "./approval.js";
import { applyDisplayFilter } from "./display.js";
import type { DisplayAdapter } from "./display.js";

/**
 * A display event yielded by `SessionHandle.submit()`.
 *
 * **BREAKING CHANGE (v0.3.0, CR-C — Mode A pivot amendment §5.2):**
 * The flat `{ type: string; sessionId; turnId; parentTurnId?; synthesized?; payload }`
 * interface has been replaced with the discriminated union below. The following
 * fields have been **removed** because the Mode A wire (subprocess + `--output json`)
 * cannot meaningfully populate them:
 *
 *   - `turnId`           — wrapper no longer correlates per-turn IDs
 *   - `parentTurnId`     — no sub-turn nesting on the Mode A wire
 *   - `synthesized`      — L14 synthesis path is removed (subprocess always returns
 *                          a final reply or non-zero exit)
 *   - `payload`          — replaced by per-variant typed fields (`text`, `code`, …)
 *
 * Migration: see `docs/designs/2026-05-24-aaa-v2-mode-a-pivot-amendment.md §5.2`
 * for the rationale and consumer migration path (NC's `ProviderEvent` mapping).
 */
export type DisplayEvent =
  | { type: "init"; sessionId: string }
  | { type: "activity" }
  | { type: "result"; text: string }
  | {
      type: "error";
      code: string;
      classification: "transport" | "protocol" | "engine" | "approval" | "unknown";
      severity: "error" | "warning";
      correlationId: string;
      message: string;
      stderrTail?: string;
      retryable: boolean;
    };

/** Typed error for AaA wrapper lifecycle and protocol violations. */
export class AaaError extends Error {
  code: string;
  remediation?: string;
  classification?: "transport" | "protocol" | "engine" | "approval" | "unknown";
  severity?: "error" | "warning";
  correlationId?: string;
  stderrTail?: string;

  constructor(
    code: string,
    remediation?: string,
    opts?: {
      classification?: AaaError["classification"];
      severity?: AaaError["severity"];
      correlationId?: string;
      stderrTail?: string;
    },
  ) {
    super(remediation ?? code);
    this.code = code;
    this.remediation = remediation;
    this.name = "AaaError";
    if (opts) {
      this.classification = opts.classification;
      this.severity = opts.severity;
      this.correlationId = opts.correlationId;
      this.stderrTail = opts.stderrTail;
    }
  }
}

/** The notification method that signals end-of-turn. */
export const TERMINAL_NOTIFICATION = "result/final";

/** Info returned by SessionHandle.getEngineInfo() (D5). */
export interface EngineInfo {
  binaryPath: string;
  protocolVersion: string;
  engineVersion: string;
  bundleDigest: string;
}

/** Dependencies injected into SessionHandle. */
export interface SessionDeps {
  sessionId: string;
  /** Called by cancel() and dispose() to SIGTERM the subprocess (D3). */
  terminate: () => Promise<unknown>;
  /** Resolved binary path (D5). Optional — defaults to empty string. */
  binaryPath?: string;
  /** Protocol version reported by the engine binary. */
  protocolVersion?: string;
  /** Engine binary version. */
  engineVersion?: string;
  /** Bundle digest from the engine version probe. */
  bundleDigest?: string;
}

/** Minimal interface for the JSON-RPC client used by SessionHandle. */
export interface RpcLike {
  call(method: string, params?: unknown): Promise<unknown>;
  onNotification(cb: (notif: { method: string; params?: unknown }) => void): void;
  /** Register a handler for a specific server-initiated request method. */
  onRequest?(method: string, handler: (params: unknown) => Promise<unknown>): void;
}

/** One-shot session handle. */
export class SessionHandle {
  private submitted = false;

  constructor(
    private readonly rpc: RpcLike,
    private readonly deps: SessionDeps,
    approval?: ApprovalAdapter,
    private readonly display?: DisplayAdapter,
  ) {
    // Wire the approval bridge if an adapter is supplied (§5.2).
    if (approval && rpc.onRequest) {
      rpc.onRequest("approval/request", makeApprovalHandler(approval));
    }
  }

  /**
   * Return resolved engine metadata (D5).
   * All fields come from the version probe run before the subprocess was spawned.
   */
  getEngineInfo(): EngineInfo {
    return {
      binaryPath: this.deps.binaryPath ?? "",
      protocolVersion: this.deps.protocolVersion ?? "",
      engineVersion: this.deps.engineVersion ?? "",
      bundleDigest: this.deps.bundleDigest ?? "",
    };
  }

  /**
   * Submit a prompt and return an AsyncIterable of DisplayEvents.
   *
   * One-shot per session (D10): throws AaaError on second call.
   */
  submit(prompt: string): AsyncIterable<DisplayEvent> {
    if (this.submitted) {
      throw new AaaError(
        "lifecycle_unsupported",
        "SessionHandle.submit() is one-shot per session (D10); already submitted",
      );
    }
    this.submitted = true;

    const { sessionId } = this.deps;
    const rand = Math.random().toString(36).slice(2);
    const turnId = `turn-${Date.now()}-${rand}`;

    return this.makeIterable(sessionId, turnId, prompt);
  }

  /**
   * Async generator that buffers display events from notification subscription
   * and terminates when result/final arrives or turn/submit response settles.
   *
   * L14 safety net: if turn/submit response contains a non-null reply and
   * result/final was never observed, synthesizes a result/final DisplayEvent
   * with synthesized: true as the last yielded event before the iterator ends.
   *
   * Display filtering: events are passed through applyDisplayFilter(display)
   * before being delivered to both the iterator and the onEvent push callback.
   */
  private async *makeIterable(
    sessionId: string,
    turnId: string,
    prompt: string,
  ): AsyncGenerator<DisplayEvent> {
    type QueueItem = DisplayEvent | null; // null = sentinel (stop)

    const queue: QueueItem[] = [];
    let wakeUp: (() => void) | null = null;
    // L14: track whether result/final notification has been observed.
    let sawFinal = false;

    // Build display filter predicate and onEvent callback reference.
    const keep = this.display !== undefined
      ? applyDisplayFilter(this.display)
      : (_ev: DisplayEvent): boolean => true;
    const onEvent = this.display?.onEvent;

    const push = (item: QueueItem): void => {
      queue.push(item);
      if (wakeUp !== null) {
        const w = wakeUp;
        wakeUp = null;
        w();
      }
    };

    // Subscribe to all notifications — filter and buffer into queue.
    this.rpc.onNotification((notif) => {
      const params = (notif.params ?? {}) as Record<string, unknown>;
      const event: DisplayEvent = {
        type: notif.method,
        sessionId: (params["sessionId"] as string | undefined) ?? sessionId,
        turnId: (params["turnId"] as string | undefined) ?? turnId,
        payload: params,
      };
      // Populate parentTurnId from payload if present.
      const parentTurnId = params["parentTurnId"] as string | undefined;
      if (parentTurnId !== undefined) {
        event.parentTurnId = parentTurnId;
      }

      // Apply display filter: only deliver kept events.
      if (!keep(event)) {
        // Event is suppressed; still check for result/final sentinel.
        if (notif.method === TERMINAL_NOTIFICATION) {
          sawFinal = true;
          push(null);
        }
        return;
      }

      // Invoke push callback before queuing (same filtered stream).
      if (onEvent !== undefined) {
        onEvent(event);
      }

      push(event);
      // result/final signals end-of-turn; push sentinel after the event.
      if (notif.method === TERMINAL_NOTIFICATION) {
        sawFinal = true;
        push(null);
      }
    });

    // Start turn/submit request.
    // On success: L14 synthesis check — if no result/final was observed and
    //   reply is non-null, push a synthesized result/final event before sentinel.
    // On error: push sentinel immediately (no reply to synthesize from).
    void this.rpc
      .call("turn/submit", { sessionId, turnId, prompt })
      .then(
        (result) => {
          const r = result as { reply?: string | null } | null;
          const reply = r != null ? (r.reply ?? null) : null;
          const syn = synthesizeFinalIfMissing({ sawFinal, reply, sessionId, turnId });
          if (syn !== null) {
            // Synthesized events always pass through (no filter for synthetic).
            if (onEvent !== undefined) {
              onEvent(syn);
            }
            push(syn);
          }
          push(null);
        },
        () => {
          // On error, still terminate the iterator.
          push(null);
        },
      );

    // Drain queue until sentinel.
    outer: while (true) {
      while (queue.length > 0) {
        const item = queue.shift();
        if (item === undefined || item === null) break outer;
        yield item;
      }
      await new Promise<void>((resolve) => {
        wakeUp = resolve;
      });
    }
  }

  /** SIGTERM the subprocess (D3). */
  async cancel(): Promise<void> {
    await this.deps.terminate();
  }

  /** Graceful shutdown; SIGTERM if needed (D3). */
  async dispose(): Promise<void> {
    await this.deps.terminate();
  }
}
