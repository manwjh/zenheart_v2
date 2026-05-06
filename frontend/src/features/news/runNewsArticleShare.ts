import { buildShareText } from "@/features/news/newsHelpers";
import type { NewsArticleDetailPayload } from "@/features/news/newsTypes";

export type NewsShareUi = {
  isWechatBrowser: boolean;
  flashCopied: () => void;
  showErrorToast: (message: string) => void;
};

export async function runNewsArticleShare(
  article: Pick<NewsArticleDetailPayload, "id" | "title" | "summary">,
  ui: NewsShareUi
): Promise<void> {
  const shareUrl = `${location.origin}/v2/share/news/${article.id}`;
  const text = buildShareText(article.title, article.summary, shareUrl);

  if (ui.isWechatBrowser) {
    try {
      await navigator.clipboard.writeText(text);
      ui.flashCopied();
    } catch {
      ui.showErrorToast("Could not copy. Check clipboard permission.");
    }
    return;
  }

  if (typeof navigator.share === "function") {
    try {
      const sum = (article.summary || "").trim();
      const shareText = sum ? `${sum}\n\n${shareUrl}` : shareUrl;
      await navigator.share({
        title: article.title,
        text: shareText,
        url: shareUrl,
      });
    } catch {
      // user cancelled
    }
    return;
  }

  try {
    await navigator.clipboard.writeText(text);
    ui.flashCopied();
  } catch {
    ui.showErrorToast("Could not copy to clipboard.");
  }
}
