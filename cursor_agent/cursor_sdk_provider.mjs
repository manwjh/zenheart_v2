#!/usr/bin/env node
import { Agent } from "@cursor/sdk";

function argValue(name, fallback = "") {
  const index = process.argv.indexOf(name);
  if (index === -1 || index + 1 >= process.argv.length) return fallback;
  return process.argv[index + 1];
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

function classifySdkError(error) {
  const chain = [error, error?.cause].filter(Boolean);
  for (const link of chain) {
    const code = link?.code;
    if (code === "unauthenticated" || code === "UNAUTHENTICATED") {
      return "unauthenticated";
    }
    const name = link?.name || "";
    if (typeof name === "string" && name.includes("Authentication")) {
      return "unauthenticated";
    }
  }
  const text = String(error?.message || error || "");
  if (/unauthenticated/i.test(text) || /authentication/i.test(text)) {
    return "unauthenticated";
  }
  return "cursor_sdk_error";
}

function emitResult(payload) {
  process.stdout.write(JSON.stringify(payload) + "\n");
}

const UNAUTH_HINT =
  "Cursor SDK rejected the request as unauthenticated. " +
  "The Cursor IDE login does NOT pass credentials to this detached Node process. " +
  "Export CURSOR_API_KEY before starting cursor_agent or add CURSOR_API_KEY=... to the env file used by --env-file " +
  "(e.g. backend/.env.zenlink-readiness). Create one under Cursor Dashboard → Integrations: https://cursor.com/dashboard/integrations";

async function main() {
  const prompt = (await readStdin()).trim();
  const apiKey = process.env.CURSOR_API_KEY?.trim();
  if (!prompt) {
    emitResult({
      ok: false,
      code: "invalid_input",
      error: "prompt is required (stdin)",
    });
    process.exitCode = 1;
    return;
  }

  const model = argValue("--model", "composer-2");
  const cwd = argValue("--cwd", process.cwd());

  const options = {
    model: { id: model },
    local: { cwd },
  };
  if (apiKey) {
    options.apiKey = apiKey;
  }

  const result = await Agent.prompt(prompt, options);

  if (result.status !== "finished") {
    emitResult({
      ok: false,
      code: "run_not_finished",
      error: `Cursor agent run did not finish: ${result.status}`,
      status: result.status,
    });
    process.exitCode = 1;
    return;
  }

  const text = String(result.result ?? "").trim();
  if (!text) {
    emitResult({
      ok: false,
      code: "empty_answer",
      error: "Cursor SDK returned an empty result",
    });
    process.exitCode = 1;
    return;
  }

  emitResult({ ok: true, text });
}

main().catch((error) => {
  const code = classifySdkError(error);
  const base = error instanceof Error ? error.message : String(error);
  emitResult({
    ok: false,
    code,
    error: code === "unauthenticated" ? UNAUTH_HINT : base,
    sdk_message: base.length < 400 ? base : base.slice(0, 400),
  });
  process.exitCode = 1;
});
