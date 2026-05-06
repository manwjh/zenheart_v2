import { ref, type Ref } from "vue";
import DOMPurify from "dompurify";
import { fetchJsonObject } from "@/composables/useJsonFetch";
import type { NewsArticleDetailPayload } from "@/features/news/newsTypes";
import { formatTextWithMentionSpansAllValid } from "@/utils/mentions";

export type NewsCommentRow = {
  id: string;
  from_type: string;
  from_agent_id: string | null;
  from_name: string | null;
  body: string;
  status: string;
  created_at: string;
};

export function useNewsComments(selectedArticle: Ref<NewsArticleDetailPayload | null>) {
  const comments = ref<NewsCommentRow[]>([]);
  const loadingComments = ref(false);
  const commentForm = ref({ name: "", body: "" });
  const commentSubmitting = ref(false);
  const commentSuccess = ref(false);
  const commentError = ref<string | null>(null);
  let commentFetchSeq = 0;

  async function fetchComments(articleId: string) {
    const seq = ++commentFetchSeq;
    loadingComments.value = true;
    try {
      const { response: res, data } = await fetchJsonObject(
        `/v2/news/articles/${articleId}/comments`
      );
      if (seq !== commentFetchSeq) return;
      if (!res.ok) {
        comments.value = [];
        return;
      }
      comments.value = Array.isArray(data.items) ? (data.items as NewsCommentRow[]) : [];
    } catch {
      if (seq === commentFetchSeq) {
        comments.value = [];
      }
    } finally {
      if (seq === commentFetchSeq) {
        loadingComments.value = false;
      }
    }
  }

  async function submitComment() {
    if (!selectedArticle.value) return;
    const name = commentForm.value.name.trim();
    const body = commentForm.value.body.trim();
    if (!body) return;

    commentSubmitting.value = true;
    commentError.value = null;
    commentSuccess.value = false;

    try {
      const res = await fetch(`/v2/news/articles/${selectedArticle.value.id}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ from_name: name || null, body }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        commentError.value =
          typeof err.detail === "string"
            ? err.detail
            : "Could not submit comment. Please try again.";
        return;
      }
      commentSuccess.value = true;
      commentForm.value = { name: "", body: "" };
      const aid = selectedArticle.value.id;
      void fetchComments(aid);
      void fetch(`/v2/news/articles/${aid}`).then(async (r) => {
        if (!r.ok) return;
        if (selectedArticle.value?.id !== aid) return;
        const d = (await r.json().catch(() => null)) as Pick<
          NewsArticleDetailPayload,
          "id" | "comment_count"
        > | null;
        if (!d || d.id !== aid || selectedArticle.value?.id !== aid) return;
        selectedArticle.value = { ...selectedArticle.value, comment_count: d.comment_count };
      });
    } catch {
      commentError.value = "Network error. Please try again.";
    } finally {
      commentSubmitting.value = false;
    }
  }

  function commentBodyHtml(body: string): string {
    return DOMPurify.sanitize(formatTextWithMentionSpansAllValid(body), {
      ALLOWED_TAGS: ["span"],
      ALLOWED_ATTR: ["class"],
    });
  }

  function resetCommentState() {
    comments.value = [];
    commentSuccess.value = false;
    commentError.value = null;
    commentForm.value = { name: "", body: "" };
  }

  return {
    comments,
    loadingComments,
    commentForm,
    commentSubmitting,
    commentSuccess,
    commentError,
    fetchComments,
    submitComment,
    commentBodyHtml,
    resetCommentState,
  };
}
