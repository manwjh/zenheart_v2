import { onUnmounted, ref } from "vue";

export function useDayTicker() {
  const tick = ref(0);
  let timer: ReturnType<typeof setInterval> | null = null;

  function start() {
    stop();
    tick.value++;
    timer = setInterval(() => {
      tick.value++;
    }, 60_000);
  }

  function stop() {
    if (!timer) return;
    clearInterval(timer);
    timer = null;
  }

  onUnmounted(stop);

  return { tick, start, stop };
}
