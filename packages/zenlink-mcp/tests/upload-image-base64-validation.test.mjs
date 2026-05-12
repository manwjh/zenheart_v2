import test from "node:test";
import assert from "node:assert/strict";

import {
  parseAgentImageBase64Argument,
  validateAgentImageBytes,
} from "../dist/zenlink/http.js";

const ONE_PX_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

test("image_base64 parser rejects invalid base64 payloads", () => {
  assert.throws(
    () => parseAgentImageBase64Argument("abcd@", "image/png"),
    /valid base64/,
  );
  assert.throws(
    () => parseAgentImageBase64Argument("abcde", "image/png"),
    /invalid base64 length/,
  );
});

test("image byte validation rejects truncated jpeg payloads", () => {
  const truncatedJpeg = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10]);
  assert.throws(
    () => validateAgentImageBytes(truncatedJpeg, "image/jpeg"),
    /truncated|complete image\/jpeg/,
  );
});

test("image byte validation accepts complete png payloads", () => {
  validateAgentImageBytes(ONE_PX_PNG, "image/png");
});
