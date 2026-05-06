import { afterEach, describe, expect, it, vi } from "vitest";
import { prefersReducedMotion, scrollBehaviorPreference } from "./motionPreference";

function stubMatchMedia(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation(() => ({
      matches,
      media: "",
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

describe("motionPreference", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("scrollBehaviorPreference is auto when reduced motion", () => {
    stubMatchMedia(true);
    expect(prefersReducedMotion()).toBe(true);
    expect(scrollBehaviorPreference()).toBe("auto");
  });

  it("scrollBehaviorPreference is smooth when motion allowed", () => {
    stubMatchMedia(false);
    expect(prefersReducedMotion()).toBe(false);
    expect(scrollBehaviorPreference()).toBe("smooth");
  });

  it("prefersReducedMotion is false if matchMedia throws", () => {
    vi.stubGlobal("matchMedia", () => {
      throw new Error("unsupported");
    });
    expect(prefersReducedMotion()).toBe(false);
    expect(scrollBehaviorPreference()).toBe("smooth");
  });
});
