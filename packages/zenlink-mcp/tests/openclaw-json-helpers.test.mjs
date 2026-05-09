import test from "node:test";
import assert from "node:assert/strict";

import {
  applyDefaultOpenClawHooksToConfig,
  DEFAULT_ZENLINK_OPENCLAW_SESSION_KEY,
} from "../scripts/openclaw-json-helpers.mjs";

test("OpenClaw hook setup adds stable default session key", () => {
  const cfg = {};

  applyDefaultOpenClawHooksToConfig(cfg);

  assert.equal(cfg.hooks.enabled, true);
  assert.equal(cfg.hooks.path, "/hooks");
  assert.equal(cfg.hooks.defaultSessionKey, DEFAULT_ZENLINK_OPENCLAW_SESSION_KEY);
  assert.equal(cfg.hooks.allowRequestSessionKey, true);
  assert.deepEqual(cfg.hooks.allowedSessionKeyPrefixes, ["hook:"]);
});

test("OpenClaw hook setup replaces legacy default session key", () => {
  const cfg = {
    hooks: {
      enabled: true,
      path: "/hooks",
      token: "existing-token",
      defaultSessionKey: "zenlink",
    },
  };

  applyDefaultOpenClawHooksToConfig(cfg);

  assert.equal(cfg.hooks.defaultSessionKey, DEFAULT_ZENLINK_OPENCLAW_SESSION_KEY);
  assert.equal(cfg.hooks.token, "existing-token");
  assert.equal(cfg.hooks.allowRequestSessionKey, true);
  assert.deepEqual(cfg.hooks.allowedSessionKeyPrefixes, ["hook:"]);
});

test("OpenClaw hook setup preserves request session routing for explicit env key", () => {
  const oldValue = process.env.ZENLINK_MCP_OPENCLAW_SESSION_KEY;
  process.env.ZENLINK_MCP_OPENCLAW_SESSION_KEY = "hook:zenheart-main";
  const cfg = {};
  try {
    applyDefaultOpenClawHooksToConfig(cfg);
  } finally {
    if (oldValue === undefined) {
      delete process.env.ZENLINK_MCP_OPENCLAW_SESSION_KEY;
    } else {
      process.env.ZENLINK_MCP_OPENCLAW_SESSION_KEY = oldValue;
    }
  }

  assert.equal(cfg.hooks.defaultSessionKey, "hook:zenheart-main");
  assert.equal(cfg.hooks.allowRequestSessionKey, true);
  assert.deepEqual(cfg.hooks.allowedSessionKeyPrefixes, ["hook:"]);
});
