<script setup lang="ts">
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
</script>

<template>
  <form class="form" @submit.prevent="emit('submit')">
    <label class="field">
      <span class="label">Email</span>
      <input
        :value="email"
        class="input"
        type="email"
        name="email"
        autocomplete="email"
        required
        placeholder="you@example.com"
        @input="emit('update:email', ($event.target as HTMLInputElement).value)"
      />
    </label>
    <label class="field">
      <span class="label">Agent name</span>
      <input
        :value="agentName"
        class="input"
        type="text"
        name="agent_name"
        minlength="2"
        maxlength="80"
        required
        placeholder="A globally unique identifier for your agent"
        @input="emit('update:agentName', ($event.target as HTMLInputElement).value)"
      />
    </label>
    <label class="field">
      <span class="label">Use-case</span>
      <textarea
        :value="reason"
        class="textarea"
        name="reason"
        rows="4"
        minlength="10"
        maxlength="4000"
        required
        placeholder="Briefly describe what your agent will do"
        @input="emit('update:reason', ($event.target as HTMLTextAreaElement).value)"
      />
    </label>
    <div class="form-footer">
      <button class="submit-btn" type="submit" :disabled="busy">
        {{ busy ? busyLabel : "Register" }}
      </button>
      <p v-if="appMessage" class="status ok" role="status">{{ appMessage }}</p>
      <p v-if="appError" class="status err" role="alert">{{ appError }}</p>
    </div>
  </form>
</template>
