/// <reference types="vite/client" />
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  build: {
    target: "es2020",
    cssCodeSplit: true,
    chunkSizeWarningLimit: 1400,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          if (
            id.includes("3d-force-graph") ||
            id.includes("three") ||
            id.includes("three-spritetext") ||
            id.includes("d3-force-3d")
          ) {
            return "graph-3d";
          }
          if (id.includes("vue-router")) return "vue-router";
          if (id.includes("/vue/") || id.endsWith("vue.js")) return "vue-core";
          if (id.includes("marked") || id.includes("dompurify")) return "md";
        },
      },
    },
  },
  server: {
    proxy: {
      "/v2": {
        target: "http://127.0.0.1:8090",
        changeOrigin: true,
        ws: true,
      },
      "/media": {
        target: "http://127.0.0.1:8090",
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
