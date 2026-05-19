<script setup lang="ts">
import { computed } from "vue";
import { ZENHEART_V2_GITHUB_REPO } from "@/features/faq/faqDocGuide";
import { faqUiByLocale, PROTOCOL_SUMMARIES } from "@/features/faq/faqCopy";
import { openFaqDocModal } from "@/features/faq/faqDocModal";
import { siteLocale } from "@/features/locale/siteLocale";

type DocItem = { slug: string; title: string; category: string; rel_path: string };

const props = defineProps<{
  docs: DocItem[];
  docsListExpanded: boolean;
  docRawUrl: (slug: string) => string;
  /** Public site root for outbound links in copy (e.g. https://zenheart.net). */
  siteHttpsOrigin: string;
}>();

const ui = computed(() => faqUiByLocale[siteLocale.value]);

function o(text: string) {
  return text.replace(/\{origin\}/g, props.siteHttpsOrigin);
}

function onProtocolDocLinkClick(e: MouseEvent, slug: string) {
  if (e.defaultPrevented) return;
  if (e.button !== 0) return;
  if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  openFaqDocModal(slug);
}

const protocolCatalogItems = computed(() => {
  const rows = props.docs.filter((d) => d.category === "protocol");
  return rows.map((row) => ({
    slug: row.slug,
    summary: PROTOCOL_SUMMARIES[siteLocale.value][row.slug] ?? "",
    title: row.title,
  }));
});

const protocolCount = computed(() => protocolCatalogItems.value.length);

const expandBtnTitle = computed(() =>
  props.docsListExpanded
    ? `${ui.value.docsCollapseTitle}（${protocolCount.value}）`
    : `${ui.value.docsExpandTitle}（${protocolCount.value}）`,
);

const emit = defineEmits<{
  toggleDocsList: [];
}>();
</script>

<template>
  <section id="docs" class="card">
    <header class="card-header card-header--split">
      <div class="card-header-main">
        <h2 class="card-title">{{ ui.docsTitle }}</h2>
        <p class="card-desc">{{ o(ui.docsP1) }}</p>
        <p class="card-desc card-desc--tight">
          {{ ui.docsSourceSite }}:
          <a :href="siteHttpsOrigin + '/'" target="_blank" rel="noopener noreferrer">{{ siteHttpsOrigin }}/</a>
          · {{ ui.docsSourceGithub }}:
          <a :href="ZENHEART_V2_GITHUB_REPO" target="_blank" rel="noopener noreferrer">{{ ZENHEART_V2_GITHUB_REPO }}</a>
          ({{ ui.docsSourceRepoNote }})
        </p>
      </div>
      <div v-if="protocolCount > 0" class="card-header-docs-toolbar">
        <button
          type="button"
          class="docs-outline-btn"
          :title="expandBtnTitle"
          :aria-label="expandBtnTitle"
          aria-controls="docs-expandable"
          :aria-expanded="docsListExpanded"
          @click="emit('toggleDocsList')"
        >
          <svg
            v-if="docsListExpanded"
            class="docs-outline-btn-icon"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <path
              d="M6 15l6-6 6 6"
              stroke="currentColor"
              stroke-width="1.75"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <svg
            v-else
            class="docs-outline-btn-icon"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <path
              d="M6 9l6 6 6-6"
              stroke="currentColor"
              stroke-width="1.75"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </button>
      </div>
    </header>

    <div v-if="docs.length === 0" class="doc-empty">
      <svg class="doc-empty-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M3 7a2 2 0 012-2h3.586a1 1 0 01.707.293L11 7h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
      <span>{{ ui.docsEmpty }}</span>
    </div>

    <div
      v-else-if="protocolCount > 0"
      v-show="docsListExpanded"
      id="docs-expandable"
      class="docs-expandable"
    >
      <div class="docs-protocol-catalog">
        <h3 class="docs-protocol-catalog-title">{{ ui.docsProtocolTitle }}</h3>
        <ul class="docs-protocol-list" role="list">
          <li
            v-for="row in protocolCatalogItems"
            :id="'doc-' + row.slug"
            :key="row.slug"
            class="docs-protocol-item"
          >
            <div class="protocol-field">
              <span class="protocol-label">{{ ui.docsProtocolNameLabel }}</span>
              <span class="protocol-value protocol-value--title">{{ row.title }}</span>
            </div>
            <div class="protocol-field">
              <span class="protocol-label">{{ ui.docsProtocolDescLabel }}</span>
              <p class="protocol-value protocol-desc">{{ row.summary }}</p>
            </div>
            <div class="protocol-field">
              <span class="protocol-label">{{ ui.docsProtocolLinkLabel }}</span>
              <a
                class="protocol-doc-url"
                :href="docRawUrl(row.slug)"
                :title="ui.docsProtocolOpenPreview"
                @click="onProtocolDocLinkClick($event, row.slug)"
                >{{ docRawUrl(row.slug) }}</a
              >
            </div>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>

<style scoped>
.docs-outline-btn { font: inherit; display: inline-flex; align-items: center; justify-content: center; padding: 0.42rem; border-radius: var(--radius-md); border: 1px solid var(--border); background: color-mix(in srgb, var(--fg) 9%, var(--bg)); color: var(--fg); cursor: pointer; line-height: 0; min-width: 2.25rem; min-height: 2.25rem; transition: background 0.12s, border-color 0.12s, color 0.12s; }
.docs-outline-btn-icon { width: 1.25rem; height: 1.25rem; display: block; flex-shrink: 0; }
.docs-outline-btn:hover:not(:disabled) { background: color-mix(in srgb, var(--fg) 16%, var(--bg)); border-color: color-mix(in srgb, var(--fg) 28%, var(--border)); }
.card-header--split { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 0.75rem 1rem; }
.card-header-main { min-width: 0; flex: 1; }
.card-header-docs-toolbar { margin-left: auto; }
.card-desc--tight { margin-top: 0.45rem; }
.docs-expandable { width: 100%; }
.docs-protocol-catalog { padding: 0 1.35rem 1rem; border-bottom: 1px solid var(--border, rgba(0, 0, 0, 0.06)); }
.docs-protocol-catalog-title { margin: 0 0 0.35rem; font-size: var(--text-strong); font-weight: 600; }
.docs-protocol-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.65rem; }
.docs-protocol-item { padding: 0.75rem 0.85rem; border-radius: var(--radius-md); border: 1px solid var(--border, rgba(0, 0, 0, 0.08)); background: rgba(var(--brand-rgb), 0.03); display: flex; flex-direction: column; gap: 0.55rem; }
.protocol-field { display: flex; flex-direction: column; gap: 0.2rem; min-width: 0; }
.protocol-label { font-size: var(--text-meta); font-weight: 600; color: var(--muted, #5c5c5c); letter-spacing: 0.02em; }
.protocol-value { margin: 0; font-size: var(--text-compact); line-height: 1.55; color: var(--fg); word-break: break-word; }
.protocol-value--title { font-size: var(--text-emphasis); font-weight: 600; }
.protocol-desc { color: var(--fg); }
.protocol-doc-url { font-size: var(--text-mono-tight); font-family: "SF Mono", ui-monospace, Consolas, monospace; color: var(--brand-accent, var(--link, #2563eb)); text-decoration: underline; text-underline-offset: 2px; word-break: break-all; }
.protocol-doc-url:hover { opacity: 0.88; }
.doc-empty { display: flex; flex-direction: column; align-items: center; gap: 0.4rem; padding: 2.5rem 1rem; color: var(--muted, #5c5c5c); font-size: var(--text-ui); }
.doc-empty-icon { width: 2rem; height: 2rem; opacity: 0.4; }
</style>
