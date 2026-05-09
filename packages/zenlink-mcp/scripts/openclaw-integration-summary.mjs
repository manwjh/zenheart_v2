/**
 * After successful `openclaw mcp set`, write a concrete integration artifact for operators.
 * LLM hosts may ignore INTEGRATION.md; this file is a paste-ready checklist next to zenlink-deploy.env.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

import { defaultOpenClawJsonPath } from "./openclaw-json-helpers.mjs";

const REDACT_KEYS =
  /TOKEN|SECRET|PASSWORD|API_KEY|ADMIN_KEY|BEARER|CREDENTIAL/i;

/**
 * @param {object} opts
 * @param {string} opts.pkgRoot Absolute path to zenlink-mcp package root (contains package.json, dist/).
 * @param {string} opts.nodeCommand Node binary written to mcp.servers.*.command
 * @param {string} opts.cliJs Absolute path to dist/cli.js
 * @param {string} opts.mcpName OpenClaw MCP server name
 * @param {Record<string, string>} opts.env Effective env merged into openclaw.json (secrets redacted in output)
 */
export function writeOpenClawIntegrationSummary(opts) {
  const { pkgRoot, nodeCommand, cliJs, mcpName, env } = opts;
  const pkg = JSON.parse(
    readFileSync(join(pkgRoot, "package.json"), "utf8"),
  );
  const version = String(pkg.version ?? "unknown");
  const openclawJson = defaultOpenClawJsonPath();
  const fromEnv = process.env.ZENLINK_MCP_INTEGRATION_SUMMARY_PATH?.trim();
  const outPath =
    fromEnv || join(dirname(pkgRoot), "zenlink-openclaw-integration-summary.md");

  const lines = [];
  for (const [k, v] of Object.entries(env)) {
    if (v === undefined || v === "") continue;
    const display = REDACT_KEYS.test(k) ? "(set, redacted)" : v;
    lines.push(`- \`${k}\`: ${display}`);
  }
  lines.sort();

  const body = `# zenlink-mcp + OpenClaw integration summary

Generated for zenlink-mcp **${version}** at **${new Date().toISOString()}**.

This file is written when \`register-openclaw.mjs\` has a final MCP \`env\` spec: after successful \`openclaw mcp set\`, **or** when the \`openclaw\` CLI is missing (exit non-zero) so you paste JSON manually — you still get this checklist. Source: \`install-openclaw.sh\` / \`npm run openclaw:register\`. Keep it with your bundle root (sibling of \`zenlink-mcp/\`, same level as \`zenlink-deploy.env\` offline). **Paste the AGENTS.md block below into your primary agent instructions** — models may not read INTEGRATION.md on their own.

## Registered MCP server

| Field | Value |
| --- | --- |
| **OpenClaw config** | \`${openclawJson}\` |
| **mcp.servers name** | \`${mcpName}\` |
| **command** | \`${nodeCommand}\` |
| **args** | \`${JSON.stringify([cliJs])}\` |

## Environment keys stored under mcp.servers.${mcpName}.env

${lines.length ? lines.join("\n") : "(none beyond defaults)"}

## If you use daemon forwarding

After registration, start the supervisor (from the directory that contains \`zenlink-mcp/\`):

\`\`\`bash
node zenlink-mcp/scripts/openclaw-zenlink-daemon.mjs start
\`\`\`

Then restart the OpenClaw Gateway so MCP workers reload.

## Quick verification

\`\`\`bash
"${nodeCommand}" "${cliJs}" --version
"${nodeCommand}" "${cliJs}" smoke
node zenlink-mcp/scripts/openclaw-zenlink-daemon.mjs status
\`\`\`

## Copy into AGENTS.md (routing — enforce in primary + sub-agent tasks)

\`\`\`text
ZenHeart / zenlink-mcp routing (strict):
- Same-channel rule: where traffic enters, handle and reply on that path. ZenHeart room work uses zenlink_join_room, zenlink_wake_drain (or zenlink_inbound_wait / zenlink_inbound_poll), zenlink_send_message. Do not use sessions_send or sessions_list to steer another ZenHeart peer.
- Room-only tasks (relay, A2A in a room): drain with room_id/current_room_only when appropriate, then reply with send_message using that frame.room_id. Do not call send_dm or get_inbox unless the user explicitly asks for private DM.
- Branch on inbound frame type: room frames -> send_message with frame.room_id; msgbox_notify -> inbox tools; do not cross wires (avoids room drift into DM or wrong-room replies).
- User spoke in this OpenClaw chat: answer here unless the user asks to use another session.
- On any system event beginning with "[ZenHeart inbound]", first call zenlink_doctor and follow agent_next_action / next_actions.
- If zenlink_doctor says drain, call zenlink_wake_drain with limit 32, timeout_ms 1000, inbox_limit 10. Decide from returned full JSON payloads, not from the hook summary. For focused room work, pass room_id/current_room_only.
- Hook message text is a nudge only. Do not reply from hook text alone unless zenlink_doctor and zenlink_wake_drain return no actionable inbound frames or msgbox backlog.
\`\`\`

## Reference

- Full operator guide: \`INTEGRATION.md\` in the zenlink-mcp source tree (ingress/egress symmetry, room vs DM drift, sub-agents). It is not always bundled inside the offline tarball; this summary is meant to stand alone.
- Disable writing this file: \`ZENLINK_MCP_WRITE_INTEGRATION_SUMMARY=0\`. Custom path: \`ZENLINK_MCP_INTEGRATION_SUMMARY_PATH=/path/to/file.md\`.
- Install verification for agents: stderr line \`ZENLINK_INSTALL_REPORT_JSON=...\` from \`register-openclaw.mjs\` (see \`install-report.mjs\`). Disable: \`ZENLINK_MCP_INSTALL_REPORT=0\`.
- Offline tarballs ship \`zenlink-bundle.manifest.json\` + \`AGENT_PLAYBOOK.md\` at bundle root (\`schemas\`, artifact list, upgrade report \`ZENLINK_UPGRADE_REPORT_JSON=\`, and phase streams \`ZENLINK_INSTALL_PHASE_JSON=\` / \`ZENLINK_UPGRADE_PHASE_JSON=\`).
`;

  writeFileSync(outPath, body, { encoding: "utf8", mode: 0o644 });
  return { outPath, version };
}
