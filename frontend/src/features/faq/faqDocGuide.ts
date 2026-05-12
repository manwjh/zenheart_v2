export const ZENHEART_V2_GITHUB_REPO = "https://github.com/manwjh/zenheart_v2";

/** Default branch for raw Markdown links in the FAQ UI. */
export const ZENHEART_V2_GITHUB_BRANCH = "main";

/** GitHub blob URL for a file under monorepo `v2/docs/` (e.g. `protocol/A01_agent-connectivity-spec.md`, `protocol/B01_*.md`). */
export function zenheartDocBlobUrlFromRelPath(relPath: string): string {
  const encoded = relPath
    .split("/")
    .map((seg) => encodeURIComponent(seg))
    .join("/");
  return `${ZENHEART_V2_GITHUB_REPO}/blob/${ZENHEART_V2_GITHUB_BRANCH}/v2/docs/${encoded}`;
}
