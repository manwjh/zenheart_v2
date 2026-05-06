<script setup lang="ts">
import { RouterView } from "vue-router";
</script>

<template>
  <RouterView v-slot="{ Component }">
    <KeepAlive include="NewsView">
      <component :is="Component" />
    </KeepAlive>
  </RouterView>
</template>
