import { ref } from "vue";
import { postNewsArticleLike } from "@/features/news/postNewsArticleLike";

export function useNewsArticleLike(onCount: (articleId: string, likeCount: number) => void) {
  const likingIds = ref<Set<string>>(new Set());

  async function likeArticle(articleId: string, event?: Event) {
    event?.stopPropagation();
    if (likingIds.value.has(articleId)) return;
    likingIds.value = new Set([...likingIds.value, articleId]);
    try {
      const count = await postNewsArticleLike(articleId);
      if (count != null) onCount(articleId, count);
    } finally {
      const next = new Set(likingIds.value);
      next.delete(articleId);
      likingIds.value = next;
    }
  }

  return { likingIds, likeArticle };
}
