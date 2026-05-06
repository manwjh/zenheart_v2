import html2canvas from "html2canvas";

/** Browser / practical canvas edge limit (html2canvas output dimensions). */
const MAX_CANVAS_EDGE = 16300;
/** Keep decoded pixel count bounded so capture returns in reasonable time on long articles. */
const TARGET_MAX_PIXELS = 9_000_000;

/** Upper bound for html2canvas + encode so the UI does not spin forever (cannot cancel the library). */
const DEFAULT_CAPTURE_DEADLINE_MS = 45_000;

function runWithDeadline<T>(promise: Promise<T>, ms: number, timeoutMessage: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const t = setTimeout(() => {
      reject(new Error(timeoutMessage));
    }, ms);
    promise.then(
      (v) => {
        clearTimeout(t);
        resolve(v);
      },
      (e) => {
        clearTimeout(t);
        reject(e);
      }
    );
  });
}

function readCssColor(el: HTMLElement, prop: string): string | null {
  const v = getComputedStyle(el).getPropertyValue(prop).trim();
  return v.length ? v : null;
}

function isTransparentCssColor(value: string): boolean {
  const s = value.trim().toLowerCase();
  return s === "transparent" || /^rgba?\(\s*0+\s*,\s*0+\s*,\s*0+\s*,\s*0\s*\)$/.test(s);
}

/** Wait for lazy/remote images so html2canvas is less likely to miss them. */
export async function waitForCaptureImages(
  root: HTMLElement,
  timeoutMs = 1200
): Promise<void> {
  const imgs = [...root.querySelectorAll("img")];
  if (!imgs.length) return;
  await Promise.race([
    Promise.all(
      imgs.map((img) => {
        // If complete, the browser has finished success or failure; do not wait on
        // load/error (they may have fired before listeners attach — would hang until race timeout).
        if (img.complete) return Promise.resolve();
        return new Promise<void>((resolve) => {
          img.addEventListener("load", () => resolve(), { once: true });
          img.addEventListener("error", () => resolve(), { once: true });
        });
      })
    ),
    new Promise<void>((resolve) => {
      setTimeout(resolve, timeoutMs);
    }),
  ]);
}

function isAbortError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const name = "name" in err ? String((err as { name: string }).name) : "";
  return name === "AbortError";
}

export async function captureNewsArticleDomToPng(element: HTMLElement): Promise<Blob> {
  const w = Math.max(1, Math.ceil(element.scrollWidth));
  const h = Math.max(1, Math.ceil(element.scrollHeight));
  const dpr = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;
  let scale = Math.min(2, dpr);
  // Cap scale so *both* output width and height stay within canvas limits (avoids huge square canvases).
  scale = Math.min(scale, MAX_CANVAS_EDGE / w, MAX_CANVAS_EDGE / h);
  const pixels = w * h * scale * scale;
  if (pixels > TARGET_MAX_PIXELS) {
    scale = Math.sqrt(TARGET_MAX_PIXELS / (w * h));
    scale = Math.min(scale, MAX_CANVAS_EDGE / w, MAX_CANVAS_EDGE / h);
  }

  let bg =
    readCssColor(element, "background-color") ||
    readCssColor(document.documentElement, "background-color") ||
    "#ffffff";
  if (isTransparentCssColor(bg)) {
    bg =
      readCssColor(document.body, "background-color") ||
      readCssColor(document.documentElement, "background-color") ||
      "#ffffff";
    if (isTransparentCssColor(bg)) bg = "#ffffff";
  }

  const canvas = await html2canvas(element, {
    scale,
    useCORS: true,
    logging: false,
    backgroundColor: bg,
    // Default 15000ms per slow image makes the button feel stuck.
    imageTimeout: 2500,
  });

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error("Could not encode image."));
      },
      "image/png",
      1
    );
  });
}

/**
 * Same as {@link captureNewsArticleDomToPng} but rejects if rendering/encode exceeds `deadlineMs`.
 * The underlying html2canvas work may still continue in the background (no public cancel API).
 */
export function captureNewsArticleDomToPngWithDeadline(
  element: HTMLElement,
  deadlineMs: number = DEFAULT_CAPTURE_DEADLINE_MS
): Promise<Blob> {
  return runWithDeadline(
    captureNewsArticleDomToPng(element),
    deadlineMs,
    "Image generation timed out. The page may be too long — try text share or try again later."
  );
}

export type LongImageShareOutcome = "shared" | "clipboard" | "download" | "cancelled";

export async function deliverNewsArticlePng(
  blob: Blob,
  filename: string,
  title: string
): Promise<LongImageShareOutcome> {
  const file = new File([blob], filename, { type: "image/png" });

  if (typeof navigator.share === "function" && typeof navigator.canShare === "function") {
    try {
      if (navigator.canShare({ files: [file] })) {
        await navigator.share({ files: [file], title });
        return "shared";
      }
    } catch (err) {
      if (isAbortError(err)) return "cancelled";
    }
  }

  if (typeof navigator.clipboard?.write === "function" && typeof ClipboardItem !== "undefined") {
    try {
      await navigator.clipboard.write([
        new ClipboardItem({ "image/png": Promise.resolve(blob) }),
      ]);
      return "clipboard";
    } catch {
      // fall through
    }
  }

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return "download";
}

export function buildNewsShareImageFilename(article: { id: string; title: string }): string {
  const raw =
    (article.title || "news")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9\u4e00-\u9fff]+/gi, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 48) || "news";
  return `${raw}-${article.id.slice(0, 8)}.png`;
}
