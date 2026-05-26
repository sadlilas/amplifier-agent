/**
 * Binary discovery, environment allowlist, and engine version probe.
 *
 * resolveBinaryPath() — find the amplifier-agent binary
 * buildEnv()          — filter subprocess env to a safe allowlist
 * probeEngineVersion() — run `amplifier-agent version --json` and parse result
 */
/** Variables always passed through to subprocess (exact name match). */
export declare const DEFAULT_ALLOWLIST: string[];
/**
 * Environment variable names that are NEVER allowed in env.extra
 * regardless of allowlist (design §4.12.1). These can be used to inject
 * code into the subprocess (e.g. via shared-library preloading or Python
 * import-path manipulation).
 */
export declare const BLOCKED_ENV_KEYS: ReadonlySet<string>;
export interface ResolveBinaryPathOptions {
    /** Environment to look up AMPLIFIER_AGENT_BIN from. Defaults to process.env. */
    env?: Record<string, string | undefined>;
}
/**
 * Resolve the path to the amplifier-agent binary.
 *
 * Resolution order:
 * 1. AMPLIFIER_AGENT_BIN env var (if set and the path exists on disk)
 * 2. `which amplifier-agent` via PATH lookup
 *
 * @throws Error with code 'binary_not_found' if neither path resolves.
 */
export declare function resolveBinaryPath(opts?: ResolveBinaryPathOptions): string;
export interface BuildEnvOptions {
    /** The caller's process environment (e.g. process.env). */
    processEnv: Record<string, string | undefined>;
    /**
     * List of exact variable names that are allowed through.
     * Variables with AMPLIFIER_ or LC_ prefixes are always included.
     */
    allowlist: string[];
    /** Additional variables merged on top (override any allowlisted value). */
    extra?: Record<string, string>;
}
/**
 * Build the subprocess environment from the caller's process environment.
 *
 * Only variables whose name is in `allowlist`, starts with `AMPLIFIER_`,
 * or starts with `LC_` are included.  `extra` entries are merged last.
 */
export declare function buildEnv(opts: BuildEnvOptions): Record<string, string>;
export interface EngineVersionPayload {
    version: string;
    protocolVersion: string;
    bundleDigest?: string;
}
/**
 * Run `<binPath> version --json` and parse the JSON response.
 *
 * @param binPath   Absolute path to the amplifier-agent binary.
 * @param env       Environment to pass to the subprocess.
 * @param timeoutMs Timeout in milliseconds (default: 5000).
 */
export declare function probeEngineVersion(binPath: string, env: Record<string, string>, timeoutMs?: number): Promise<EngineVersionPayload>;
