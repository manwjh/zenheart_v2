import { computed, ref } from "vue";
import { clipCurlDownloadMarkdown } from "@/features/faq/faqHelpers";

export interface FaqDocItem {
  slug: string;
  title: string;
  category: string;
  rel_path: string;
}

type RenderMarkdown = (raw: string) => Promise<string>;

export function useFaqDocs(renderMarkdown: RenderMarkdown) {
  /** Full catalog is opt-in so the FAQ page stays approachable. */
  const docsListExpanded = ref(false);
  const docs = ref<FaqDocItem[]>([]);
  const expandedSlug = ref<string | null>(null);
  const docContent = ref<Record<string, string>>({});
  const docLoading = ref<Record<string, boolean>>({});
  const docError = ref<Record<string, string>>({});
  const copiedSlug = ref<string | null>(null);

  const docApiBase = computed(() =>
    typeof window !== "undefined" ? `${window.location.origin}/v2/faq/docs` : "/v2/faq/docs",
  );
  function toggleDocsList() {
    docsListExpanded.value = !docsListExpanded.value;
  }

  function docRawUrl(slug: string) {
    return `${docApiBase.value}/${encodeURIComponent(slug)}`;
  }

  async function loadDocLists() {
    const res = await fetch("/v2/faq/docs");
    if (res.ok) {
      const raw = (await res.json()) as FaqDocItem[];
      docs.value = raw.map((d) => ({
        slug: d.slug,
        title: d.title,
        category: d.category ?? "",
        rel_path: d.rel_path ?? "",
      }));
    }
  }

  async function toggleDoc(slug: string) {
    if (expandedSlug.value === slug) {
      expandedSlug.value = null;
      return;
    }
    expandedSlug.value = slug;
    if (docContent.value[slug]) return;
    docLoading.value = { ...docLoading.value, [slug]: true };
    try {
      const res = await fetch(docRawUrl(slug));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = await res.text();
      docContent.value = {
        ...docContent.value,
        [slug]: await renderMarkdown(raw),
      };
    } catch (e) {
      docError.value = {
        ...docError.value,
        [slug]: e instanceof Error ? e.message : "Failed to load document.",
      };
    } finally {
      docLoading.value = { ...docLoading.value, [slug]: false };
    }
  }

  async function copyDocLink(slug: string) {
    try {
      await navigator.clipboard.writeText(clipCurlDownloadMarkdown(docRawUrl(slug), `${slug}.md`));
      copiedSlug.value = slug;
      setTimeout(() => {
        if (copiedSlug.value === slug) copiedSlug.value = null;
      }, 2000);
    } catch {
      // ignore
    }
  }

  return {
    docsListExpanded,
    docs,
    expandedSlug,
    docContent,
    docLoading,
    docError,
    copiedSlug,
    docApiBase,
    toggleDocsList,
    docRawUrl,
    loadDocLists,
    toggleDoc,
    copyDocLink,
  };
}
