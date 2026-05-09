<script setup lang="ts">
import { computed } from "vue";
import { faqUiByLocale } from "@/features/faq/faqCopy";
import { siteLocale } from "@/features/locale/siteLocale";

defineProps<{
  email: string;
  agentName: string;
  reason: string;
  busy: boolean;
  busyLabel: string;
  appMessage: string | null;
  appError: string | null;
}>();

const emit = defineEmits<{
  submit: [];
  "update:email": [value: string];
  "update:agentName": [value: string];
  "update:reason": [value: string];
}>();

const ui = computed(() => faqUiByLocale[siteLocale.value]);
</script>

<template>
  <form class="form" @submit.prevent="emit('submit')">
    <label class="field">
      <span class="label">{{ ui.formEmail }}</span>
      <input
        :value="email"
        class="input"
        type="email"
        name="email"
        autocomplete="email"
        required
        :placeholder="ui.formPhEmail"
        @input="emit('update:email', ($event.target as HTMLInputElement).value)"
      />
    </label>
    <label class="field">
      <span class="label">{{ ui.formDisplayName }}</span>
      <input
        :value="agentName"
        class="input"
        type="text"
        name="agent_name"
        minlength="2"
        maxlength="80"
        required
        :placeholder="ui.formPhName"
        @input="emit('update:agentName', ($event.target as HTMLInputElement).value)"
      />
    </label>
    <label class="field">
      <span class="label">{{ ui.formUseCase }}</span>
      <textarea
        :value="reason"
        class="textarea"
        name="reason"
        rows="4"
        minlength="10"
        maxlength="4000"
        required
        :placeholder="ui.formPhReason"
        @input="emit('update:reason', ($event.target as HTMLTextAreaElement).value)"
      />
    </label>
    <div class="form-footer">
      <button class="submit-btn" type="submit" :disabled="busy">
        {{ busy ? busyLabel : ui.formSubmit }}
      </button>
      <p v-if="appMessage" class="status ok" role="status">{{ appMessage }}</p>
      <p v-if="appError" class="status err" role="alert">{{ appError }}</p>
    </div>
  </form>
</template>
