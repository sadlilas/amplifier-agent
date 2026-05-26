/**
 * Protocol version check for the Amplifier Agent wrapper.
 *
 * checkProtocolVersion() compares the wrapper's compiled protocol version
 * constant against the version reported by the engine binary.
 *
 * On mismatch it returns ok=false with a remediation hint.
 * The check can be bypassed with allowSkew=true.
 */
/**
 * Compare wrapper and engine protocol versions.
 *
 * @returns VersionCheckOk if they match, or if allowSkew is true.
 * @returns VersionCheckFail if they mismatch and allowSkew is false/unset.
 */
export function checkProtocolVersion(opts) {
    const { wrapper, engine, allowSkew = false } = opts;
    if (allowSkew || wrapper === engine) {
        return { ok: true };
    }
    return {
        ok: false,
        code: "protocol_version_mismatch",
        remediation: `Protocol version mismatch: wrapper expects '${wrapper}' but engine reports '${engine}'. ` +
            `Install a compatible engine version or set allowProtocolSkew: true / ` +
            `AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW=1 to allow-protocol-skew.`,
    };
}
