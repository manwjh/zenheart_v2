<script setup lang="ts">
import { computed } from "vue";
import { FAQ_PROTOCOL_DOCS, ZENHEART_V2_GITHUB_REPO, zenheartDocBlobUrl } from "@/features/faq/faqDocGuide";
import { faqUiByLocale, PROTOCOL_SUMMARIES } from "@/features/faq/faqCopy";
import { siteLocale } from "@/features/locale/siteLocale";

type DocItem = { slug: string; title: string };

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

const docTitleBySlug = computed(() => {
  const m = new Map<string, string>();
  for (const d of props.docs) m.set(d.slug, d.title);
  return m;
});

const protocolCatalogItems = computed(() =>
  FAQ_PROTOCOL_DOCS.map((row) => ({
    file: row.file,
    slug: row.slug,
    summary: PROTOCOL_SUMMARIES[siteLocale.value][row.slug] ?? "",
    title: docTitleBySlug.value.get(row.slug) ?? row.slug,
    githubUrl: zenheartDocBlobUrl(row.file),
  })),
);

const expandBtnTitle = computed(() =>
  props.docsListExpanded
    ? `${ui.value.docsCollapseTitle}（${props.docs.length}）`
    : `${ui.value.docsExpandTitle}（${props.docs.length}）`,
);

const emit = defineEmits<{
  toggleDocsList: [];
  copyDocLink: [slug: string];
  toggleDoc: [slug: string];
  jumpToDoc: [slug: string];
}>();
</script>

<template>
  <section id="docs" class="card">
    <header class="card-header card-header--split">
      <div class="card-header-main">
        <h2 class="card-title">{{ ui.docsTitle }}</h2>
        <p class="card-desc">{{ o(ui.docsP1) }}</p>
        <p class="card-desc card-desc--tight">
          <template v-if="siteLocale === 'zh'">
            站点入口：<a :href="siteHttpsOrigin + '/'" target="_blank" rel="noopener noreferrer">{{ siteHttpsOrigin }}/</a>
            · GitHub：
            <a :href="ZENHEART_V2_GITHUB_REPO" target="_blank" rel="noopener noreferrer">{{ ZENHEART_V2_GITHUB_REPO }}</a>
            （树内 <code>v2/docs/</code> 与线上一致时，仍以运行时与 OpenAPI 为准）。日常对接不必克隆整仓。
          </template>
          <template v-else>
            Site:
            <a :href="siteHttpsOrigin + '/'" target="_blank" rel="noopener noreferrer">{{ siteHttpsOrigin }}/</a>
            · GitHub:
            <a :href="ZENHEART_V2_GITHUB_REPO" target="_blank" rel="noopener noreferrer">{{ ZENHEART_V2_GITHUB_REPO }}</a>
            (when <code>v2/docs/</code> matches production, runtime + OpenAPI still win). No need to clone the monorepo for
            day-to-day integration.
          </template>
        </p>
        <p class="card-desc card-desc--tight">{{ o(ui.docsP3) }}</p>
      </div>
      <div v-if="docs.length > 0" class="card-header-docs-toolbar">
        <button
          type="button"
          class="docs-outline-btn"
          :title="expandBtnTitle"
          aria-controls="docs-main-list"
          :aria-expanded="docsListExpanded"
          @click="emit('toggleDocsList')"
        >
          {{ docsListExpanded ? ui.docsCollapseAll : ui.docsExpandAll }}
        </button>
      </div>
    </header>

    <div v-if="docs.length > 0" class="docs-protocol-catalog">
      <h3 class="docs-protocol-catalog-title">{{ ui.docsProtocolTitle }}</h3>
      <p class="docs-protocol-catalog-lead">{{ o(ui.docsProtocolLead) }}</p>
      <ul class="docs-protocol-list" role="list">
        <li v-for="row in protocolCatalogItems" :key="row.slug" class="docs-protocol-item">
          <div class="docs-protocol-head">
            <code class="docs-protocol-file" :title="row.file">{{ row.file }}</code>
            <span class="docs-protocol-doc-title">{{ row.title }}</span>
          </div>
          <p class="docs-protocol-summary">{{ row.summary }}</p>
          <div class="docs-protocol-meta">
            <code class="docs-protocol-slug">{{ row.slug }}</code>
            <div class="docs-protocol-actions">
              <a class="docs-protocol-link" :href="row.githubUrl" target="_blank" rel="noopener noreferrer">GitHub</a>
              <button type="button" class="docs-protocol-jump" @click="emit('jumpToDoc', row.slug)">
                {{ ui.docsFullFaq }}
              </button>
            </div>
          </div>
        </li>
      </ul>
    </div>

    <div v-if="docs.length === 0" class="doc-empty">
      <svg class="doc-empty-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M3 7a2 2 0 012-2h3.586a1 1 0 01.707.293L11 7h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
      <span>{{ ui.docsEmpty }}</span>
    </div>

    <ul v-else v-show="docsListExpanded" id="docs-main-list" class="doc-list" role="list">
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
  </section>
</template>

<style scoped>
.docs-outline-btn { font: inherit; font-size: var(--text-compact); font-weight: 600; letter-spacing: 0.02em; padding: 0.4rem 0.75rem; border-radius: var(--radius-md); border: 1px solid var(--border); background: color-mix(in srgb, var(--fg) 9%, var(--bg)); color: var(--fg); cursor: pointer; line-height: 1.2; min-height: 2.25rem; transition: background 0.12s, border-color 0.12s, color 0.12s; }
.docs-outline-btn:hover:not(:disabled) { background: color-mix(in srgb, var(--fg) 16%, var(--bg)); border-color: color-mix(in srgb, var(--fg) 28%, var(--border)); }
.card-header--split { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 0.75rem 1rem; }
.card-header-main { min-width: 0; flex: 1; }
.card-header-docs-toolbar { margin-left: auto; }
.card-desc--tight { margin-top: 0.45rem; }
.docs-protocol-catalog { padding: 0 1.35rem 1rem; border-bottom: 1px solid var(--border, rgba(0, 0, 0, 0.06)); }
.docs-protocol-catalog-title { margin: 0 0 0.35rem; font-size: var(--text-strong); font-weight: 600; }
.docs-protocol-catalog-lead { margin: 0 0 0.85rem; font-size: var(--text-compact); color: var(--muted, #5c5c5c); line-height: 1.5; }
.docs-protocol-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.65rem; }
.docs-protocol-item { padding: 0.65rem 0.75rem; border-radius: var(--radius-md); border: 1px solid var(--border, rgba(0, 0, 0, 0.08)); background: rgba(var(--brand-rgb), 0.03); }
.docs-protocol-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.4rem 0.75rem; margin-bottom: 0.35rem; }
.docs-protocol-file { font-size: var(--text-mono-tight); font-family: "SF Mono", ui-monospace, Consolas, monospace; color: var(--muted, #5c5c5c); }
.docs-protocol-doc-title { font-size: var(--text-emphasis); font-weight: 600; }
.docs-protocol-summary { margin: 0 0 0.45rem; font-size: var(--text-compact); line-height: 1.55; color: var(--fg); }
.docs-protocol-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem 0.75rem; justify-content: space-between; }
.docs-protocol-slug { font-size: var(--text-mono-tight); font-family: "SF Mono", ui-monospace, Consolas, monospace; color: var(--muted, #5c5c5c); }
.docs-protocol-actions { display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: center; }
.docs-protocol-link { font-size: var(--text-meta); font-weight: 600; color: inherit; }
.docs-protocol-jump { font: inherit; font-size: var(--text-meta); font-weight: 600; padding: 0.28rem 0.55rem; border-radius: var(--radius-md); border: 1px solid var(--border); background: color-mix(in srgb, var(--fg) 8%, var(--bg)); color: inherit; cursor: pointer; }
.docs-protocol-jump:hover { background: color-mix(in srgb, var(--fg) 14%, var(--bg)); }
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
