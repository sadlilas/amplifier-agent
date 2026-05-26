/**
 * Result of resolving the `--mcp-servers` flag value.
 *
 * - When `mcpServers` is null/undefined/empty: both fields are `null`.
 * - When no server has a non-empty env block: `flag` is inline JSON,
 *   `spillPath` is `null` (no cleanup needed).
 * - When any server has a non-empty env block: `flag` is `@<spillPath>`,
 *   `spillPath` points at the 0600 tmpfile (caller must cleanup).
 */
export interface McpSpillResult {
    flag: string | null;
    spillPath: string | null;
}
/**
 * Loose shape for an MCP server entry. We only inspect `env` here; the rest
 * is threaded through untouched into the spilled JSON or inline payload.
 */
interface McpServerLike {
    env?: Record<string, string> | undefined;
    [k: string]: unknown;
}
type McpServersMap = Record<string, McpServerLike>;
/**
 * Resolve the value to pass for `--mcp-servers`.
 *
 * @param mcpServers Map of server-id -> config, or null/undefined.
 * @param sessionId  Session identifier; used as the per-session subdirectory
 *                   under the spill base so concurrent sessions never clash.
 *
 * @returns A `McpSpillResult` with the flag value and (if spilled) the
 *          on-disk path for later cleanup.
 */
export declare function resolveMcpServersFlag(mcpServers: McpServersMap | null | undefined, sessionId: string): Promise<McpSpillResult>;
/**
 * Idempotently remove a spill file. Safe to call with `null` (no-op) and
 * safe to call when the file is already gone (ENOENT swallowed). Other
 * I/O errors propagate.
 */
export declare function cleanupSpillFile(spillPath: string | null | undefined): Promise<void>;
export {};
