export function formatErrorDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: unknown) => {
        if (d && typeof d === "object" && "msg" in d) {
          return String((d as { msg: string }).msg);
        }
        return "";
      })
      .filter(Boolean)
      .join("; ");
  }
  return "";
}

export function stripSkillFrontmatter(raw: string): string {
  const t = raw.trimStart();
  if (!t.startsWith("---")) return raw;
  const rest = t.slice(3);
  const end = rest.indexOf("\n---");
  if (end === -1) return raw;
  return rest.slice(end + 4).trimStart();
}

function bashSingleQuoted(value: string): string {
  return value.replace(/'/g, `'\\''`);
}

export function clipCurlDownloadFile(url: string, outFile: string): string {
  return `curl -fsSL '${bashSingleQuoted(url)}' -o '${bashSingleQuoted(outFile)}'`;
}

export function clipCurlDownloadMarkdown(url: string, outFile: string): string {
  return clipCurlDownloadFile(url, outFile);
}
