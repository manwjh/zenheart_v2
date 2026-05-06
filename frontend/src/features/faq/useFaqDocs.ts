import { computed, ref } from "vue";
import { clipCurlDownloadMarkdown } from "@/features/faq/faqHelpers";

export interface FaqDocItem {
  slug: string;
  title: string;
}

type RenderMarkdown = (raw: string) => Promise<string>;

export function useFaqDocs(renderMarkdown: RenderMarkdown) {
  const docsListExpanded = ref(true);
  const docs = ref<FaqDocItem[]>([]);
  const gameRuleDocs = ref<FaqDocItem[]>([]);
  const expandedSlug = ref<string | null>(null);
  const docContent = ref<Record<string, string>>({});
  const docLoading = ref<Record<string, boolean>>({});
  const docError = ref<Record<string, string>>({});
  const copiedSlug = ref<string | null>(null);

  const docApiBase = computed(() =>
    typeof window !== "undefined" ? `${window.location.origin}/v2/faq/docs` : "/v2/faq/docs",
  );
  const gameDocApiBase = computed(() =>
    typeof window !== "undefined" ? `${window.location.origin}/v2/faq/game` : "/v2/faq/game",
  );

  function toggleDocsList() {
    docsListExpanded.value = !docsListExpanded.value;
  }

  function docRawUrl(slug: string) {
    return `${docApiBase.value}/${encodeURIComponent(slug)}`;
  }

  function gameDocRawUrl(slug: string) {
    return `${gameDocApiBase.value}/${encodeURIComponent(slug)}`;
  }

  async function loadDocLists() {
    const [docsResult, gameDocsResult] = await Promise.allSettled([
      fetch("/v2/faq/docs"),
      fetch("/v2/faq/game"),
    ]);
    if (docsResult.status === "fulfilled" && docsResult.value.ok) {
      docs.value = (await docsResult.value.json()) as FaqDocItem[];
    }
    if (gameDocsResult.status === "fulfilled" && gameDocsResult.value.ok) {
      gameRuleDocs.value = (await gameDocsResult.value.json()) as FaqDocItem[];
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
    gameRuleDocs,
    expandedSlug,
    docContent,
    docLoading,
    docError,
    copiedSlug,
    docApiBase,
    gameDocApiBase,
    toggleDocsList,
    docRawUrl,
    gameDocRawUrl,
    loadDocLists,
    toggleDoc,
    copyDocLink,
  };
}
