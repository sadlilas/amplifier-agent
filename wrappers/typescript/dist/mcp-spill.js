/**
 * mcp-spill.ts — secret-aware MCP servers config resolution (CR-A).
 *
 * A3'/CR-A: When forwarding `--mcp-servers` to the engine binary, the wrapper
 * must avoid placing secret-bearing env blocks on the command line. If any
 * server in the config has a non-empty `env` block, the full JSON is spilled
 * to a 0600 tmpfile under `${XDG_RUNTIME_DIR || os.tmpdir()}/amplifier-agent/<sessionId>/`
 * and the flag value is `@<path>`. When no server has env, the JSON is inlined
 * directly (no spill, no cleanup needed).
 *
 * `cleanupSpillFile` is the matching teardown — idempotent unlink that
 * swallows ENOENT so callers can call it unconditionally on every exit path.
 */
import { mkdir, writeFile, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
/**
 * Return true when at least one server has a non-empty `env` block.
 * An empty object (`{}`) does NOT trigger spilling — only env blocks with
 * at least one key are considered secret-bearing.
 */
function anyServerHasEnv(mcpServers) {
    for (const key of Object.keys(mcpServers)) {
        const server = mcpServers[key];
        if (!server)
            continue;
        const env = server.env;
        if (env && typeof env === "object" && Object.keys(env).length > 0) {
            return true;
        }
    }
    return false;
}
/**
 * Compute the base directory for spill files. Prefers
 * `$XDG_RUNTIME_DIR/amplifier-agent` (typically a tmpfs on Linux) and falls
 * back to `os.tmpdir()/amplifier-agent` otherwise.
 */
function spillBaseDir() {
    const xdg = process.env["XDG_RUNTIME_DIR"];
    if (xdg && xdg.length > 0) {
        return join(xdg, "amplifier-agent");
    }
    return join(tmpdir(), "amplifier-agent");
}
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
export async function resolveMcpServersFlag(mcpServers, sessionId) {
    if (!mcpServers || Object.keys(mcpServers).length === 0) {
        return { flag: null, spillPath: null };
    }
    if (!anyServerHasEnv(mcpServers)) {
        // No secrets — safe to inline as a JSON string.
        return { flag: JSON.stringify(mcpServers), spillPath: null };
    }
    // Secret-bearing: spill to a 0600 tmpfile under a 0700 per-session dir.
    const dir = join(spillBaseDir(), sessionId);
    await mkdir(dir, { recursive: true, mode: 0o700 });
    const filePath = join(dir, "mcp.json");
    await writeFile(filePath, JSON.stringify(mcpServers), { mode: 0o600 });
    return { flag: `@${filePath}`, spillPath: filePath };
}
/**
 * Idempotently remove a spill file. Safe to call with `null` (no-op) and
 * safe to call when the file is already gone (ENOENT swallowed). Other
 * I/O errors propagate.
 */
export async function cleanupSpillFile(spillPath) {
    if (!spillPath)
        return;
    try {
        await unlink(spillPath);
    }
    catch (err) {
        const code = err.code;
        if (code === "ENOENT")
            return;
        throw err;
    }
}
