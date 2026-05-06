/** Whether the user asked for less motion (OS / browser setting). */
export function prefersReducedMotion(): boolean {
  if (typeof matchMedia === "undefined") return false;
  try {
    return matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/** `scrollIntoView` `behavior` that respects `prefers-reduced-motion`. */
export function scrollBehaviorPreference(): "smooth" | "auto" {
  return prefersReducedMotion() ? "auto" : "smooth";
}
