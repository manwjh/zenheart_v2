import { writeFileSync, mkdtempSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import test from "node:test";
import assert from "node:assert/strict";

import {
  readAgentImageBytesFromResolvedPath,
} from "../dist/tools/upload-image-from-path.js";

const ONE_PX_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

function restoreEnv(keys) {
  const saved = {};
  for (const k of keys) {
    saved[k] = process.env[k];
  }
  return () => {
    for (const k of keys) {
      if (saved[k] === undefined) {
        delete process.env[k];
      } else {
        process.env[k] = saved[k];
      }
    }
  };
}

test("image_path rejected when ZENLINK_MCP_UPLOAD_IMAGE_FS is off", () => {
  const done = restoreEnv([
    "ZENLINK_MCP_UPLOAD_IMAGE_FS",
    "ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT",
    "ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOTS",
  ]);
  try {
    delete process.env.ZENLINK_MCP_UPLOAD_IMAGE_FS;
    delete process.env.ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT;
    delete process.env.ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOTS;
    assert.throws(
      () => readAgentImageBytesFromResolvedPath("/any/path.png", undefined),
      /image_path is disabled/,
    );
  } finally {
    done();
  }
});

test("image_path requires allowed roots when FS is on", () => {
  const done = restoreEnv([
    "ZENLINK_MCP_UPLOAD_IMAGE_FS",
    "ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT",
    "ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOTS",
  ]);
  try {
    process.env.ZENLINK_MCP_UPLOAD_IMAGE_FS = "1";
    delete process.env.ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT;
    delete process.env.ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOTS;
    assert.throws(
      () => readAgentImageBytesFromResolvedPath("/etc/passwd", "image/png"),
      /requires ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT/,
    );
  } finally {
    done();
  }
});

test("image_path accepts file inside configured root", () => {
  const done = restoreEnv([
    "ZENLINK_MCP_UPLOAD_IMAGE_FS",
    "ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT",
    "ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOTS",
  ]);
  const base = mkdtempSync(join(tmpdir(), "zenlink-upload-fs-"));
  const inbound = join(base, "inbound");
  mkdirSync(inbound, { recursive: true });
  const f = join(inbound, "x.png");
  writeFileSync(f, ONE_PX_PNG);
  try {
    process.env.ZENLINK_MCP_UPLOAD_IMAGE_FS = "1";
    process.env.ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT = base;
    delete process.env.ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOTS;
    const r = readAgentImageBytesFromResolvedPath(f, undefined);
    assert.equal(r.contentType, "image/png");
    assert.ok(r.defaultFilename.endsWith(".png"));
    assert.equal(Buffer.from(r.data).compare(ONE_PX_PNG), 0);
  } finally {
    done();
  }
});

test("image_path rejects file outside configured root", () => {
  const done = restoreEnv([
    "ZENLINK_MCP_UPLOAD_IMAGE_FS",
    "ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT",
    "ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOTS",
  ]);
  const base = mkdtempSync(join(tmpdir(), "zenlink-upload-fs-o-"));
  const other = mkdtempSync(join(tmpdir(), "zenlink-upload-fs-other-"));
  const f = join(other, "x.png");
  writeFileSync(f, ONE_PX_PNG);
  try {
    process.env.ZENLINK_MCP_UPLOAD_IMAGE_FS = "1";
    process.env.ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT = base;
    delete process.env.ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOTS;
    assert.throws(
      () => readAgentImageBytesFromResolvedPath(f, undefined),
      /outside configured allowed roots/,
    );
  } finally {
    done();
  }
});
