import { ref } from "vue";

/** Track broken cover URLs so we can show the placeholder instead. */
export function useArticleCover() {
  const failedCovers = ref<Set<string>>(new Set());

  function markCoverFailed(id: string) {
    if (failedCovers.value.has(id)) return;
    failedCovers.value = new Set([...failedCovers.value, id]);
  }

  function showCover(item: { id: string; cover_image_url: string }): boolean {
    return !!item.cover_image_url && !failedCovers.value.has(item.id);
  }

  function resetFailedCovers() {
    failedCovers.value = new Set();
  }

  return { markCoverFailed, showCover, resetFailedCovers };
}
