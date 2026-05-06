<script setup lang="ts">
type DocItem = { slug: string; title: string };

defineProps<{
  docs: DocItem[];
  gameRuleDocs: DocItem[];
  docsListExpanded: boolean;
  expandedSlug: string | null;
  docContent: Record<string, string>;
  docLoading: Record<string, boolean>;
  docError: Record<string, string>;
  copiedSlug: string | null;
  gameDocApiBase: string;
  docRawUrl: (slug: string) => string;
  gameDocRawUrl: (slug: string) => string;
}>();

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
        <h2 class="card-title">Docs</h2>
        <p class="card-desc">
          <strong>Copy</strong> gives a terminal one-liner (<code>curl -fsSL ... -o &lt;slug&gt;.md</code>). Or
          fetch the URL in code: <code>fetch(url).then(r =&gt; r.text())</code>.
        </p>
      </div>
      <div v-if="docs.length > 0" class="card-header-docs-toolbar">
        <button
          type="button"
          class="docs-outline-btn"
          :title="docsListExpanded ? 'Collapse document list' : 'Expand document list'"
          aria-controls="docs-main-list"
          :aria-expanded="docsListExpanded"
          @click="emit('toggleDocsList')"
        >
          {{ docsListExpanded ? "▲" : "▼" }}
        </button>
      </div>
    </header>

    <div v-if="docs.length === 0" class="doc-empty">
      <svg class="doc-empty-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M3 7a2 2 0 012-2h3.586a1 1 0 01.707.293L11 7h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
      <span>No documents available yet.</span>
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
              :title="copiedSlug === doc.slug ? 'Copied!' : 'curl one-liner — paste in terminal to save as ' + doc.slug + '.md'"
              @click="emit('copyDocLink', doc.slug)"
            >
              {{ copiedSlug === doc.slug ? "Copied!" : "Copy" }}
            </button>
            <a class="action-btn download-btn" :href="`/v2/faq/docs/${encodeURIComponent(doc.slug)}`" :download="`${doc.slug}.md`" title="Download as .md file">
              Download
            </a>
            <button
              class="action-btn read-btn"
              :class="{ active: expandedSlug === doc.slug }"
              :title="expandedSlug === doc.slug ? 'Collapse' : 'Read inline'"
              @click="emit('toggleDoc', doc.slug)"
            >
              {{ expandedSlug === doc.slug ? "Close ▲" : "Read ▼" }}
            </button>
          </div>
        </div>

        <div v-if="expandedSlug === doc.slug" class="doc-reader">
          <div v-if="docLoading[doc.slug]" class="reader-status">Loading…</div>
          <div v-else-if="docError[doc.slug]" class="reader-status err">{{ docError[doc.slug] }}</div>
          <div v-else class="markdown-body" v-html="docContent[doc.slug]" />
        </div>
      </li>
    </ul>

    <div v-if="gameRuleDocs.length > 0" class="game-rules-sub">
      <h3 class="game-rules-title">Game rules</h3>
      <p class="card-desc">
        Placed in <code>v2/games/</code> in the repo (not <code>v2/docs/</code>) — POMDP models, scoring, WebSocket field reference. Raw:
        <code>{{ gameDocApiBase }}</code>
      </p>
      <ul class="doc-list" role="list">
        <li v-for="g in gameRuleDocs" :key="'g-' + g.slug" class="doc-item">
          <div class="doc-row">
            <div class="doc-meta">
              <span class="doc-title">{{ g.title }}</span>
              <span class="doc-url">{{ gameDocRawUrl(g.slug) }}</span>
            </div>
            <div class="doc-actions">
              <a class="action-btn download-btn" :href="gameDocRawUrl(g.slug)" :download="`${g.slug}.md`" title="Download as .md file">
                Download
              </a>
            </div>
          </div>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.docs-outline-btn { font: inherit; font-size: var(--text-compact); font-weight: 600; letter-spacing: 0.02em; padding: 0.4rem 0.75rem; border-radius: var(--radius-md); border: 1px solid var(--border); background: color-mix(in srgb, var(--fg) 9%, var(--bg)); color: var(--fg); cursor: pointer; line-height: 1.2; min-height: 2.25rem; transition: background 0.12s, border-color 0.12s, color 0.12s; }
.docs-outline-btn:hover:not(:disabled) { background: color-mix(in srgb, var(--fg) 16%, var(--bg)); border-color: color-mix(in srgb, var(--fg) 28%, var(--border)); }
.card-header--split { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 0.75rem 1rem; }
.card-header-main { min-width: 0; flex: 1; }
.card-header-docs-toolbar { margin-left: auto; }
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
.game-rules-sub { margin-top: 1rem; border-top: 1px dashed var(--border, rgba(0, 0, 0, 0.12)); padding-top: 1rem; }
.game-rules-title { margin: 0 0 0.5rem; font-size: var(--text-strong); font-weight: 600; }
</style>
