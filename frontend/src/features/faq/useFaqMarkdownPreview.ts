import { marked } from "marked";
import DOMPurify from "dompurify";

/** Relative URL for plain-text FAQ markdown (same origin). */
export function faqDocRawPath(slug: string): string {
  return `/v2/faq/docs/${encodeURIComponent(slug.trim())}`;
}

/** Fetch FAQ doc markdown and return sanitized HTML for preview. */
export async function fetchFaqMarkdownAsHtml(slug: string, signal?: AbortSignal): Promise<string> {
  const res = await fetch(faqDocRawPath(slug), { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const raw = await res.text();
  return DOMPurify.sanitize(await marked.parse(raw));
}
