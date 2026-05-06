import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { ZENLINK_MCP_TOOL_NAMES_SORTED } from "../tools/tool-permissions-map.js";

/** Canonical MCP tool list; defined in `../tools/tool-permissions-map.ts`. */
export const EXPECTED_TOOL_NAMES = ZENLINK_MCP_TOOL_NAMES_SORTED;

function listsEqual(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((name, i) => name === b[i]);
}

export async function runSmokeStdioTools(): Promise<number> {
  const __dirname = dirname(fileURLToPath(import.meta.url));
  const cliJs = join(__dirname, "..", "cli.js");

  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [cliJs],
    env: {
      ...process.env,
      ZENLINK_MCP_LONG_LIVED: "0",
      ZENLINK_AGENT_ID:
        process.env.ZENLINK_AGENT_ID ??
        process.env.ZENHEART_AGENT_ID ??
        process.env.ZENHEART_V2_AGENT_ID ??
        "smoke_test_agent",
      ZENLINK_TOKEN:
        process.env.ZENLINK_TOKEN ??
        process.env.ZENHEART_TOKEN ??
        process.env.ZENHEART_V2_TOKEN ??
        "smoke_test_token",
    },
    stderr: "inherit",
  });

  const client = new Client({
    name: "zenlink-mcp-smoke",
    version: "0.0.1",
  });

  await client.connect(transport);

  const { tools } = await client.listTools();
  const names = tools.map((t) => t.name).sort();

  if (!listsEqual(names, [...EXPECTED_TOOL_NAMES])) {
    console.error(
      "FAIL: tools/list must exactly match the canonical tool set (see tool-permissions-map.ts).",
    );
    console.error("expected count:", EXPECTED_TOOL_NAMES.length, "got:", names.length);
    console.error("expected:", [...EXPECTED_TOOL_NAMES].join(", "));
    console.error("actual:  ", names.join(", "));
    await transport.close();
    return 1;
  }

  console.log("PASS: tools/list count =", names.length);
  console.log(names.join("\n"));

  await transport.close();
  return 0;
}
