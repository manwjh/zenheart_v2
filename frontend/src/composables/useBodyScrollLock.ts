import { watch, type Ref } from "vue";

export function useBodyScrollLock(active: Ref<boolean>) {
  watch(
    active,
    (isActive) => {
      document.body.style.overflow = isActive ? "hidden" : "";
    },
    { immediate: true },
  );
}
