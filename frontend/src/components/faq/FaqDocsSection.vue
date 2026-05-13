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
  expandedSlug: string | null;
  docContent: Record<string, string>;
  docLoading: Record<string, boolean>;
  docError: Record<string, string>;
  copiedSlug: string | null;
  docRawUrl: (slug: string) => string;
  /** Public site root for outbound links in copy (e.g. https://zenheart.net). */
  siteHttpsOrigin: string;
}>();

const ui = computed(() => faqUiByLocale[siteLocale.value]);

function o(text: string) {
  return text.replace(/\{origin\}/g, props.siteHttpsOrigin);
}

function curlTitle(slug: string) {
  return ui.value.docsCurlTitle.replace(/\{slug\}/g, slug);
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

const expandBtnTitle = computed(() =>
  props.docsListExpanded
    ? `${ui.value.docsCollapseTitle}（${props.docs.length}）`
    : `${ui.value.docsExpandTitle}（${props.docs.length}）`,
);

const emit = defineEmits<{
  toggleDocsList: [];
  copyDocLink: [slug: string];
  toggleDoc: [slug: string];
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
      <div v-if="docs.length > 0" class="card-header-docs-toolbar">
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
      v-else
      v-show="docsListExpanded"
      id="docs-expandable"
      class="docs-expandable"
    >
      <div class="docs-protocol-catalog">
        <h3 class="docs-protocol-catalog-title">{{ ui.docsProtocolTitle }}</h3>
        <ul class="docs-protocol-list" role="list">
          <li v-for="row in protocolCatalogItems" :key="row.slug" class="docs-protocol-item">
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

      <ul id="docs-main-list" class="doc-list" role="list">
        <li v-for="doc in docs" :id="'doc-' + doc.slug" :key="doc.slug" class="doc-item">
          <div class="doc-row">
            <div class="doc-meta">
              <span class="doc-title">{{ doc.title }}</span>
              <span class="doc-url">{{ docRawUrl(doc.slug) }}</span>
            </div>
            <div class="doc-actions">
              <button
                class="action-btn copy-btn"
                :class="{ copied: copiedSlug === doc.slug }"
                :title="copiedSlug === doc.slug ? ui.docsCopied : curlTitle(doc.slug)"
                @click="emit('copyDocLink', doc.slug)"
              >
                {{ copiedSlug === doc.slug ? ui.docsCopied : ui.docsCopy }}
              </button>
              <a
                class="action-btn download-btn"
                :href="`/v2/faq/docs/${encodeURIComponent(doc.slug)}`"
                :download="`${doc.slug}.md`"
                :title="ui.docsDownloadTitle"
              >
                {{ ui.docsDownload }}
              </a>
              <button
                class="action-btn read-btn"
                :class="{ active: expandedSlug === doc.slug }"
                :title="expandedSlug === doc.slug ? ui.docsClose : ui.docsRead"
                @click="emit('toggleDoc', doc.slug)"
              >
                {{ expandedSlug === doc.slug ? ui.docsClose : ui.docsRead }}
              </button>
            </div>
          </div>

          <div v-if="expandedSlug === doc.slug" class="doc-reader">
            <div v-if="docLoading[doc.slug]" class="reader-status">{{ ui.docsLoading }}</div>
            <div v-else-if="docError[doc.slug]" class="reader-status err">{{ docError[doc.slug] }}</div>
            <div v-else class="markdown-body" v-html="docContent[doc.slug]" />
          </div>
        </li>
      </ul>
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
.doc-list { list-style: none; margin: 0; padding: 0; }
.doc-item { border-bottom: 1px solid var(--border, rgba(0, 0, 0, 0.06)); }
.doc-item:last-child { border-bottom: none; }
.doc-row { display: flex; align-items: center; gap: 1rem; padding: 0.9rem 1.35rem; flex-wrap: wrap; }
.doc-meta { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.2rem; }
.doc-title { font-size: var(--text-emphasis); font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.doc-url { font-size: var(--text-mono-tight); font-family: "SF Mono", ui-monospace, Consolas, monospace; color: var(--muted, #5c5c5c); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.doc-actions { display: flex; gap: 0.4rem; flex-shrink: 0; flex-wrap: wrap; }
.action-btn { border: 1px solid var(--border, rgba(0, 0, 0, 0.12)); border-radius: var(--radius-md); background: transparent; color: inherit; font: inherit; font-size: var(--text-meta); line-height: 1; padding: 0.42rem 0.62rem; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; transition: background 0.12s, border-color 0.12s, color 0.12s; }
.action-btn:hover { background: rgba(0, 0, 0, 0.05); }
.copy-btn.copied { border-color: #15803d; color: #15803d; background: rgba(21, 128, 61, 0.06); }
.read-btn.active { background: rgba(0, 0, 0, 0.06); border-color: rgba(0, 0, 0, 0.15); }
.doc-reader { padding: 1rem 1.35rem 1.25rem; border-top: 1px solid var(--border, rgba(0, 0, 0, 0.06)); background: rgba(0, 0, 0, 0.015); }
.reader-status { font-size: var(--text-ui); color: var(--muted, #5c5c5c); }
.reader-status.err { color: var(--error); }
.markdown-body {
  font-size: var(--text-emphasis);
  line-height: 1.7;
  color: inherit;
  min-width: 0;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}
.markdown-body :deep(p) { margin: 0 0 0.8rem; }
.markdown-body :deep(pre) {
  max-width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}
.markdown-body :deep(code) { font-size: var(--text-compact); font-family: "SF Mono", ui-monospace, Consolas, monospace; padding: 0.1em 0.38em; border-radius: var(--radius-xs); background: rgba(0, 0, 0, 0.06); }
</style>
