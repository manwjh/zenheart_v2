import { ref, watch } from "vue";
import { fetchJsonObject } from "@/composables/useJsonFetch";
import { formatErrorDetail } from "@/features/faq/faqHelpers";
import { faqUiByLocale } from "@/features/faq/faqCopy";
import { siteLocale } from "@/features/locale/siteLocale";

export function useFaqApplication() {
  const email = ref("");
  const agentName = ref("");
  const reason = ref("");
  const busy = ref(false);
  const busyLabel = ref(faqUiByLocale[siteLocale.value].busyVerifying);
  const appMessage = ref<string | null>(null);
  const appError = ref<string | null>(null);

  watch(siteLocale, () => {
    if (busy.value) busyLabel.value = faqUiByLocale[siteLocale.value].busyVerifying;
  });

  async function submitApplication() {
    appMessage.value = null;
    appError.value = null;
    busy.value = true;
    busyLabel.value = faqUiByLocale[siteLocale.value].busyVerifying;
    try {
      const { response: res, data } = await fetchJsonObject("/v2/faq/agent-application", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.value.trim(),
          agent_name: agentName.value.trim(),
          reason: reason.value.trim(),
        }),
      });
      if (!res.ok) {
        appError.value = formatErrorDetail(data.detail) || res.statusText;
        return;
      }
      const name = typeof data.agent_name === "string" ? data.agent_name : agentName.value.trim();
      appMessage.value =
        typeof data.message === "string"
          ? data.message
          : `Registration successful! Please check your email — we're looking forward to ${name}'s first connection.`;
      email.value = "";
      agentName.value = "";
      reason.value = "";
    } catch (e) {
      appError.value = e instanceof Error ? e.message : faqUiByLocale[siteLocale.value].networkError;
    } finally {
      busy.value = false;
    }
  }

  return {
    email,
    agentName,
    reason,
    busy,
    busyLabel,
    appMessage,
    appError,
    submitApplication,
  };
}
