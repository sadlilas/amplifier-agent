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
/**
 * Create a JSON-RPC request handler for 'approval/request'.
 *
 * @param adapter - Host-supplied adapter, or undefined for default-deny.
 * @returns An async function (params) => ApprovalResponse.
 */
export function makeApprovalHandler(adapter) {
    if (!adapter) {
        return async (_params) => ({
            decision: "deny",
            reason: "no_adapter_configured",
        });
    }
    const { onRequest, timeoutMs } = adapter;
    return async (params) => {
        let timerId;
        const timeoutPromise = new Promise((resolve) => {
            timerId = setTimeout(() => {
                resolve({ decision: "timeout" });
            }, timeoutMs);
        });
        try {
            const result = await Promise.race([onRequest(params), timeoutPromise]);
            // Clear the timeout timer if onRequest won the race.
            if (timerId !== undefined)
                clearTimeout(timerId);
            return result;
        }
        catch {
            if (timerId !== undefined)
                clearTimeout(timerId);
            return { decision: "deny", reason: "adapter_error" };
        }
    };
}
