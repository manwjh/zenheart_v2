import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

import {
  getEffectiveParticipantRules,
  getParticipantRulesSnapshotForTools,
  isParticipantRulesWriteEnabled,
} from "../dist/social/participant-rules.js";

function withEnv(patch, fn) {
  const before = {};
  for (const key of Object.keys(patch)) before[key] = process.env[key];
  for (const [key, value] of Object.entries(patch)) {
    if (value === null) delete process.env[key];
    else process.env[key] = value;
  }
  try {
    return fn();
  } finally {
    for (const key of Object.keys(patch)) {
      const v = before[key];
      if (v === undefined) delete process.env[key];
      else process.env[key] = v;
    }
  }
}

test("effective participant rules prefer file over env", () => {
  const dir = mkdtempSync(join(tmpdir(), "zenlink-prules-"));
  const file = join(dir, "rules.txt");
  writeFileSync(file, "file rules", "utf8");
  try {
    withEnv(
      {
        ZENLINK_MCP_PARTICIPANT_RULES_FILE: file,
        ZENLINK_MCP_PARTICIPANT_RULES: "env rules",
      },
      () => {
        const r = getEffectiveParticipantRules();
        assert.equal(r.source, "file");
        assert.equal(r.text, "file rules");
        assert.equal(r.participant_rules_file_missing, false);
      },
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("effective participant rules fallback to env when file missing", () => {
  withEnv(
    {
      ZENLINK_MCP_PARTICIPANT_RULES_FILE:
        "/tmp/non-existent-participant-rules.txt",
      ZENLINK_MCP_PARTICIPANT_RULES: "env\\nrules",
    },
    () => {
      const r = getEffectiveParticipantRules();
      assert.equal(r.source, "env");
      assert.equal(r.text, "env\nrules");
      assert.equal(r.participant_rules_file_missing, true);
    },
  );
});

test("write flag and snapshot reflect env", () => {
  withEnv(
    {
      ZENLINK_MCP_PARTICIPANT_RULES_WRITE: "on",
      ZENLINK_MCP_PARTICIPANT_RULES: "abc",
      ZENLINK_MCP_PARTICIPANT_RULES_FILE: null,
    },
    () => {
      assert.equal(isParticipantRulesWriteEnabled(), true);
      const snap = getParticipantRulesSnapshotForTools();
      assert.equal(snap.write_enabled, true);
      assert.equal(snap.participant_rules_source, "env");
      assert.equal(snap.participant_rules, "abc");
    },
  );
});
