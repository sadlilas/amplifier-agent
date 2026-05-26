/**
 * Approval bridge — in-band, mid-turn JSON-RPC round-trip (§5.2).
 *
 * makeApprovalHandler(adapter) returns a JSON-RPC request handler for
 * 'approval/request' server-initiated requests. Wire it into the
 * JsonRpcClient via rpc.onRequest('approval/request', makeApprovalHandler(adapter)).
 *
 * Decision semantics:
 *   - 'allow'   — adapter accepted the tool call
 *   - 'deny'    — adapter rejected, adapter threw, or no adapter configured
 *   - 'timeout' — adapter did not resolve within timeoutMs
 *
 * Pattern reference: Design §5.2 — six-step round-trip.
 */
/** Request sent by the engine when a tool call requires approval. */
export interface ApprovalRequest {
    id: string;
    tool: string;
    args: unknown;
}
/** Response the wrapper sends back to the engine. */
export interface ApprovalResponse {
    decision: "allow" | "deny" | "timeout";
    reason?: string;
    [key: string]: unknown;
}
/** Adapter supplied by the host to handle approval requests. */
export interface ApprovalAdapter {
    onRequest: (req: unknown) => Promise<ApprovalResponse>;
    timeoutMs: number;
}
/** Handler type matching JsonRpcClient.onRequest signature. */
export type ApprovalHandler = (params: unknown) => Promise<unknown>;
/**
 * Create a JSON-RPC request handler for 'approval/request'.
 *
 * @param adapter - Host-supplied adapter, or undefined for default-deny.
 * @returns An async function (params) => ApprovalResponse.
 */
export declare function makeApprovalHandler(adapter: ApprovalAdapter | undefined): ApprovalHandler;
