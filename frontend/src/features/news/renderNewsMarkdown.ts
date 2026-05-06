import DOMPurify from "dompurify";
import { marked } from "marked";

let configured = false;

function ensureMarkedConfigured(): void {
  if (configured) return;
  marked.setOptions({
    gfm: true,
    breaks: true,
  });
  configured = true;
}

export function renderNewsMarkdown(markdown: string): string {
  ensureMarkedConfigured();
  return DOMPurify.sanitize(marked.parse(markdown) as string);
}
