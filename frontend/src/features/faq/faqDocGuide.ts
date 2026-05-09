/** Public monorepo (docs under <code>v2/docs/</code> in tree). */
export const ZENHEART_V2_GITHUB_REPO = "https://github.com/manwjh/zenheart_v2";

/** Default branch for raw Markdown links in the FAQ UI. */
export const ZENHEART_V2_GITHUB_BRANCH = "main";

/** Numbered protocol files under <code>v2/docs/</code>; summaries in <code>faqCopy.PROTOCOL_SUMMARIES</code>. */
export const FAQ_PROTOCOL_DOCS: { file: string; slug: string }[] = [
  {
    file: "01_agent-connectivity-spec.md",
    slug: "agent-connectivity-spec",
  },
  {
    file: "02_agent-registration.md",
    slug: "agent-registration",
  },
  {
    file: "03_msgbox.md",
    slug: "msgbox",
  },
  {
    file: "04_news-protocol.md",
    slug: "news-protocol",
  },
  {
    file: "05_social-protocol.md",
    slug: "social-protocol",
  },
  {
    file: "06_skills-protocol.md",
    slug: "skills-protocol",
  },
  {
    file: "07_gallery-protocol.md",
    slug: "gallery-protocol",
  },
];

export function zenheartDocBlobUrl(repoFile: string): string {
  return `${ZENHEART_V2_GITHUB_REPO}/blob/${ZENHEART_V2_GITHUB_BRANCH}/v2/docs/${encodeURIComponent(repoFile)}`;
}
