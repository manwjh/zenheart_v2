import { describe, expect, it } from "vitest";
import {
  formatTextWithMentionSpans,
  formatTextWithMentionSpansAllValid,
  formatTextWithMentionSpansWithHints,
} from "./mentions";

describe("mentions formatter", () => {
  it("escapes html and keeps non-mention text", () => {
    const out = formatTextWithMentionSpans("hello <script>x</script>", () => false);
    expect(out).toContain("&lt;script&gt;x&lt;/script&gt;");
  });

  it("formats authoritative mention by predicate", () => {
    const out = formatTextWithMentionSpans("hi @Alice", (name) => name === "alice");
    expect(out).toContain('class="text-mention text-mention--valid"');
    expect(out).toContain("@Alice");
  });

  it("supports hint-based mention classes", () => {
    const out = formatTextWithMentionSpansWithHints("one @A two @B", (name) =>
      name === "a" ? "authoritative" : "room_only",
    );
    expect(out).toContain("text-mention--valid");
    expect(out).toContain("text-mention--room");
  });

  it("marks all @tokens valid in all-valid helper", () => {
    const out = formatTextWithMentionSpansAllValid("@one @two");
    expect(out.match(/text-mention--valid/g)?.length).toBe(2);
  });

  it("supports braced display-name mention syntax", () => {
    const out = formatTextWithMentionSpansWithHints("hi @{王哥}", (name) =>
      name === "王哥" ? "authoritative" : "stray",
    );
    expect(out).toContain("text-mention--valid");
    expect(out).toContain("@{王哥}");
  });

  it("supports display text override with title", () => {
    const out = formatTextWithMentionSpansWithHints("hi @AGN-abc", () => ({
      hint: "authoritative",
      displayText: "@Rockman",
      title: "@AGN-abc",
    }));
    expect(out).toContain("@Rockman");
    expect(out).toContain('title="@AGN-abc"');
  });
});
