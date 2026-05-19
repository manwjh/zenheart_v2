import { computed, ref } from "vue";

export interface FaqDocItem {
  slug: string;
  title: string;
  category: string;
  rel_path: string;
}

export function useFaqDocs() {
  /** Full catalog is opt-in so the FAQ page stays approachable. */
  const docsListExpanded = ref(false);
  const docs = ref<FaqDocItem[]>([]);

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

  return {
    docsListExpanded,
    docs,
    docApiBase,
    toggleDocsList,
    docRawUrl,
    loadDocLists,
  };
}
