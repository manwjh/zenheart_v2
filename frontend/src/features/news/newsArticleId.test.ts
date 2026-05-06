import { describe, expect, it } from "vitest";
import { isNewsArticleId } from "./newsArticleId";

describe("isNewsArticleId", () => {
  it("accepts lowercase UUID strings", () => {
    expect(
      isNewsArticleId("550e8400-e29b-41d4-a716-446655440000")
    ).toBe(true);
  });

  it("accepts uppercase hex", () => {
    expect(
      isNewsArticleId("550E8400-E29B-41D4-A716-446655440000")
    ).toBe(true);
  });

  it("rejects slug-like paths", () => {
    expect(isNewsArticleId("archive")).toBe(false);
    expect(isNewsArticleId("my-article")).toBe(false);
  });

  it("rejects wrong segment lengths", () => {
    expect(isNewsArticleId("550e8400-e29b-41d4-a716-44665544000")).toBe(false);
  });

  it("trims whitespace", () => {
    expect(isNewsArticleId("  550e8400-e29b-41d4-a716-446655440000  ")).toBe(
      true
    );
  });

  it("rejects nullish", () => {
    expect(isNewsArticleId(null)).toBe(false);
    expect(isNewsArticleId(undefined)).toBe(false);
  });
});
