import { ref } from "vue";

/** When set, `FaqMarkdownPreviewModal` in `App.vue` loads and renders that FAQ doc slug. */
export const faqDocModalSlug = ref<string | null>(null);

export function openFaqDocModal(slug: string): void {
  const trimmed = slug.trim();
  if (!trimmed) return;
  faqDocModalSlug.value = trimmed;
}

export function closeFaqDocModal(): void {
  faqDocModalSlug.value = null;
}
