#!/usr/bin/env node
/**
 * One-shot WebSocket `auth` check using env credentials.
 * Run after build: `node dist/cli.js`, or install the package dir globally / link by path.
 */
import { createZenlinkFromEnv } from "./client.js";

function usage(): void {
  const msg = `Usage: node dist/cli.js   (from built zenlink package)

Connect to ZenHeart v2, send auth, print auth_ok and exit 0; otherwise exit 1.

Environment (required — any one column for id / token):

  ZENLINK_AGENT_ID        or  ZENHEART_AGENT_ID  /  ZENHEART_V2_AGENT_ID
  ZENLINK_TOKEN           or  ZENHEART_TOKEN  /  ZENHEART_V2_TOKEN

Host defaults to production (zenheart.net). Optional override (self-hosted / staging):
  ZENLINK_HOST            or  ZENHEART_HOST  /  ZENHEART_V2_HOST

Other optional:
  ZENLINK_USE_TLS         (or ZENHEART_USE_TLS) — 0 or false for ws://
  ZENLINK_CHANNEL         (or ZENHEART_CHANNEL) — agent (default) | social
`;
  console.error(msg);
}

async function main(): Promise<void> {
  if (process.argv.includes("--help") || process.argv.includes("-h")) {
    usage();
    process.exit(0);
  }
  let client;
  try {
    client = createZenlinkFromEnv();
  } catch (e) {
    const m = e instanceof Error ? e.message : String(e);
    console.error(m);
    usage();
    process.exit(1);
  }
  try {
    const ok = await client.connect();
    console.log(
      JSON.stringify(
        {
          ok: true,
          agent_id: ok.agent_id,
          level: ok.level,
          connection_id: ok.connection_id,
          server_time: ok.server_time,
        },
        null,
        2
      )
    );
    client.close(1000);
    process.exit(0);
  } catch (e) {
    if (e instanceof Error) {
      console.error(e.message);
    } else {
      console.error(String(e));
    }
    client?.close(1000);
    process.exit(1);
  }
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
});
