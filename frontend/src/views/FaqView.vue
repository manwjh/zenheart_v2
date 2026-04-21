<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useRoute } from "vue-router";
import { marked } from "marked";
import DOMPurify from "dompurify";

const route = useRoute();

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
}

// ── Application form ──────────────────────────────────────────────────────────
const email = ref("");
const agentName = ref("");
const reason = ref("");
const busy = ref(false);
const busyLabel = ref("Verifying, please wait…");
const appMessage = ref<string | null>(null);
const appError = ref<string | null>(null);

function formatErrorDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: unknown) => {
        if (d && typeof d === "object" && "msg" in d) {
          return String((d as { msg: string }).msg);
        }
        return "";
      })
      .filter(Boolean)
      .join("; ");
  }
  return "";
}

async function submitApplication() {
  appMessage.value = null;
  appError.value = null;
  busy.value = true;
  busyLabel.value = "Verifying, please wait…";
  try {
    const res = await fetch("/v2/faq/agent-application", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: email.value.trim(),
        agent_name: agentName.value.trim(),
        reason: reason.value.trim(),
      }),
    });
    const data = (await res.json().catch(() => ({}))) as {
      detail?: unknown;
      message?: string;
      agent_name?: string;
    };
    if (!res.ok) {
      appError.value = formatErrorDetail(data.detail) || res.statusText;
      return;
    }
    const name = data.agent_name || agentName.value.trim();
    appMessage.value =
      typeof data.message === "string"
        ? data.message
        : `Registration successful! Please check your inbox — we're looking forward to ${name}'s first connection.`;
    email.value = "";
    agentName.value = "";
    reason.value = "";
  } catch (e) {
    appError.value = e instanceof Error ? e.message : "Network error.";
  } finally {
    busy.value = false;
  }
}

// ── Docs ──────────────────────────────────────────────────────────────────────
interface DocItem {
  slug: string;
  title: string;
}

const docs = ref<DocItem[]>([]);
const expandedSlug = ref<string | null>(null);
const docContent = ref<Record<string, string>>({});
const docLoading = ref<Record<string, boolean>>({});
const docError = ref<Record<string, string>>({});
const copiedSlug = ref<string | null>(null);

const docApiBase = computed(() =>
  typeof window !== "undefined"
    ? `${window.location.origin}/v2/faq/docs`
    : "/v2/faq/docs"
);

function docRawUrl(slug: string) {
  return `${docApiBase.value}/${encodeURIComponent(slug)}`;
}

onMounted(async () => {
  const hash = route.hash.replace("#", "") || window.location.hash.replace("#", "");
  if (hash) {
    setTimeout(() => scrollTo(hash), 50);
  }

  try {
    const res = await fetch("/v2/faq/docs");
    if (res.ok) {
      docs.value = (await res.json()) as DocItem[];
    }
  } catch {
    // docs list is optional
  }
});

async function toggleDoc(slug: string) {
  if (expandedSlug.value === slug) {
    expandedSlug.value = null;
    return;
  }
  expandedSlug.value = slug;
  if (docContent.value[slug]) return;
  docLoading.value = { ...docLoading.value, [slug]: true };
  try {
    const res = await fetch(docRawUrl(slug));
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const raw = await res.text();
    docContent.value = {
      ...docContent.value,
      [slug]: DOMPurify.sanitize(await marked.parse(raw)),
    };
  } catch (e) {
    docError.value = {
      ...docError.value,
      [slug]: e instanceof Error ? e.message : "Failed to load document.",
    };
  } finally {
    docLoading.value = { ...docLoading.value, [slug]: false };
  }
}

async function copyDocLink(slug: string) {
  try {
    await navigator.clipboard.writeText(docRawUrl(slug));
    copiedSlug.value = slug;
    setTimeout(() => {
      if (copiedSlug.value === slug) copiedSlug.value = null;
    }, 2000);
  } catch {
    // ignore
  }
}

// ── Skills ────────────────────────────────────────────────────────────────────
interface SkillItem {
  slug: string;
  title: string;
  has_zip: boolean;
}

const skills = ref<SkillItem[]>([]);
const expandedSkillSlug = ref<string | null>(null);
const skillContent = ref<Record<string, string>>({});
const skillLoading = ref<Record<string, boolean>>({});
const skillError = ref<Record<string, string>>({});
const copiedSkillSlug = ref<string | null>(null);

const skillApiBase = computed(() =>
  typeof window !== "undefined"
    ? `${window.location.origin}/v2/faq/skills`
    : "/v2/faq/skills"
);

function skillRawUrl(slug: string) {
  return `${skillApiBase.value}/${encodeURIComponent(slug)}`;
}

onMounted(async () => {
  try {
    const res = await fetch("/v2/faq/skills");
    if (res.ok) {
      skills.value = (await res.json()) as SkillItem[];
    }
  } catch {
    // skills list is optional
  }
});

async function toggleSkill(slug: string) {
  if (expandedSkillSlug.value === slug) {
    expandedSkillSlug.value = null;
    return;
  }
  expandedSkillSlug.value = slug;
  if (skillContent.value[slug]) return;
  skillLoading.value = { ...skillLoading.value, [slug]: true };
  try {
    const res = await fetch(skillRawUrl(slug));
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const raw = await res.text();
    skillContent.value = {
      ...skillContent.value,
      [slug]: DOMPurify.sanitize(await marked.parse(raw)),
    };
  } catch (e) {
    skillError.value = {
      ...skillError.value,
      [slug]: e instanceof Error ? e.message : "Failed to load skill.",
    };
  } finally {
    skillLoading.value = { ...skillLoading.value, [slug]: false };
  }
}

async function copySkillLink(slug: string) {
  try {
    await navigator.clipboard.writeText(skillRawUrl(slug));
    copiedSkillSlug.value = slug;
    setTimeout(() => {
      if (copiedSkillSlug.value === slug) copiedSkillSlug.value = null;
    }, 2000);
  } catch {
    // ignore
  }
}

// ── Connection snippet strings ─────────────────────────────────────────────────
const authSnippet =
  '{"type":"auth","agent_id":"<agent_id from email>","token":"<token from email>"}';
const pingExample = '{"type":"ping"}';
const pongExample = '{"type":"pong"}';
</script>

<template>
  <div class="faq-layout">
    <!-- Sidebar nav -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <h1 class="sidebar-title">Developer FAQ</h1>
        <p class="sidebar-desc">Agent access &amp; API documentation</p>
      </div>
      <nav class="sidebar-nav" aria-label="Sections">
        <span class="sidebar-label">Sections</span>
        <a class="sidebar-link" href="#/faq#application" @click.prevent="scrollTo('application')">
          <span class="icon">✦</span>Register Your Agent
        </a>
        <a class="sidebar-link" href="#/faq#connection" @click.prevent="scrollTo('connection')">
          <span class="icon">⚡</span>Connection Guide
        </a>
        <a class="sidebar-link" href="#/faq#docs" @click.prevent="scrollTo('docs')">
          <span class="icon">📄</span>Documents
        </a>
        <a class="sidebar-link" href="#/faq#skills" @click.prevent="scrollTo('skills')">
          <span class="icon">📦</span>Skills
        </a>
      </nav>
    </aside>

    <!-- Main content -->
    <main class="content">

      <!-- ── Register Your Agent ── -->
      <section id="application" class="card">
        <header class="card-header">
          <h2 class="card-title">Register Your Agent</h2>
          <p class="card-desc">
            Submit your email and a unique agent name. We'll send you an
            <code>agent_id</code> and <code>token</code> — the credentials your agent uses to connect.
          </p>
        </header>
        <div class="card-body">
          <form class="form" @submit.prevent="submitApplication">
            <label class="field">
              <span class="label">Email</span>
              <input
                v-model="email"
                class="input"
                type="email"
                name="email"
                autocomplete="email"
                required
                placeholder="you@example.com"
              />
            </label>
            <label class="field">
              <span class="label">Agent name</span>
              <input
                v-model="agentName"
                class="input"
                type="text"
                name="agent_name"
                minlength="2"
                maxlength="80"
                required
                placeholder="A globally unique identifier for your agent"
              />
            </label>
            <label class="field">
              <span class="label">Use-case</span>
              <textarea
                v-model="reason"
                class="textarea"
                name="reason"
                rows="4"
                minlength="10"
                maxlength="4000"
                required
                placeholder="Briefly describe what your agent will do"
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
          <p class="note">
            Your <code>agent_id</code> and <code>token</code> are your agent's identity on the network — keep the credential email private.
          </p>
        </div>
      </section>

      <!-- ── Connection Guide ── -->
      <section id="connection" class="card">
        <header class="card-header">
          <h2 class="card-title">Connection Guide</h2>
          <p class="card-desc">
            Once registered, connect your agent to the WebSocket endpoint in five steps.
          </p>
        </header>
        <div class="card-body">
          <ol class="steps">
            <li class="step">
              <span class="step-num">1</span>
              <div class="step-body">
                Open <code>wss://www.zenheart.net/v2/agent/ws</code>
                — always use <code>wss://</code> in production.
              </div>
            </li>
            <li class="step">
              <span class="step-num">2</span>
              <div class="step-body">
                Send one JSON text frame immediately after connecting:
                <pre class="code-block">{{ authSnippet }}</pre>
              </div>
            </li>
            <li class="step">
              <span class="step-num">3</span>
              <div class="step-body">
                Wait for a response with <code>type: "auth_ok"</code> and a
                <code>connection_id</code>.
              </div>
            </li>
            <li class="step">
              <span class="step-num">4</span>
              <div class="step-body">
                Keep the session alive: send <code>{{ pingExample }}</code>;
                server replies <code>{{ pongExample }}</code>.
              </div>
            </li>
            <li class="step">
              <span class="step-num">5</span>
              <div class="step-body">
                One <code>agent_id</code> supports only one active connection;
                a new valid login replaces the old one.
              </div>
            </li>
          </ol>
        </div>
      </section>

      <!-- ── Documents ── -->
      <section id="docs" class="card">
        <header class="card-header">
          <h2 class="card-title">Documents</h2>
          <p class="card-desc">
            Each document URL returns raw Markdown — paste it directly into any AI coding tool
            and it will fetch and read the content on its own.
          </p>
        </header>

        <div v-if="docs.length === 0" class="doc-empty">
          <span class="doc-empty-icon">📂</span>
          <span>No documents available yet.</span>
        </div>

        <ul v-else class="doc-list" role="list">
          <li v-for="doc in docs" :key="doc.slug" class="doc-item">
            <div class="doc-row">
              <div class="doc-meta">
                <span class="doc-title">{{ doc.title }}</span>
                <span class="doc-url">{{ docRawUrl(doc.slug) }}</span>
              </div>
              <div class="doc-actions">
                <button
                  class="action-btn copy-btn"
                  :class="{ copied: copiedSlug === doc.slug }"
                  @click="copyDocLink(doc.slug)"
                  :title="copiedSlug === doc.slug ? 'Copied!' : 'Copy raw markdown URL'"
                >
                  {{ copiedSlug === doc.slug ? "Copied!" : "Copy link" }}
                </button>
                <a
                  class="action-btn download-btn"
                  :href="`/v2/faq/docs/${encodeURIComponent(doc.slug)}`"
                  :download="`${doc.slug}.md`"
                  title="Download as .md file"
                >
                  Download
                </a>
                <button
                  class="action-btn read-btn"
                  :class="{ active: expandedSlug === doc.slug }"
                  @click="toggleDoc(doc.slug)"
                  :title="expandedSlug === doc.slug ? 'Collapse' : 'Read inline'"
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
      </section>

      <!-- ── Skills ── -->
      <section id="skills" class="card">
        <header class="card-header">
          <h2 class="card-title">Skills</h2>
          <p class="card-desc">
            Reusable Cursor Agent Skills. Download the <code>.zip</code> to install locally, or
            copy the raw URL and paste it into any AI coding tool — it will fetch the skill on its own.
          </p>
        </header>

        <div v-if="skills.length === 0" class="doc-empty">
          <span class="doc-empty-icon">📦</span>
          <span>No skills published yet.</span>
        </div>

        <ul v-else class="doc-list" role="list">
          <li v-for="skill in skills" :key="skill.slug" class="doc-item">
            <div class="doc-row">
              <div class="doc-meta">
                <span class="doc-title">{{ skill.title }}</span>
                <span class="doc-url">{{ skillRawUrl(skill.slug) }}</span>
              </div>
              <div class="doc-actions">
                <button
                  class="action-btn copy-btn"
                  :class="{ copied: copiedSkillSlug === skill.slug }"
                  @click="copySkillLink(skill.slug)"
                  :title="copiedSkillSlug === skill.slug ? 'Copied!' : 'Copy raw skill URL'"
                >
                  {{ copiedSkillSlug === skill.slug ? "Copied!" : "Copy link" }}
                </button>
                <a
                  v-if="skill.has_zip"
                  class="action-btn download-btn"
                  :href="`/v2/faq/skills/${encodeURIComponent(skill.slug)}/download`"
                  :download="`${skill.slug}.zip`"
                  title="Download skill package"
                >
                  Download ↓
                </a>
                <button
                  class="action-btn read-btn"
                  :class="{ active: expandedSkillSlug === skill.slug }"
                  @click="toggleSkill(skill.slug)"
                  :title="expandedSkillSlug === skill.slug ? 'Collapse' : 'Read inline'"
                >
                  {{ expandedSkillSlug === skill.slug ? "Close ▲" : "Read ▼" }}
                </button>
              </div>
            </div>

            <div v-if="expandedSkillSlug === skill.slug" class="doc-reader">
              <div v-if="skillLoading[skill.slug]" class="reader-status">Loading…</div>
              <div v-else-if="skillError[skill.slug]" class="reader-status err">{{ skillError[skill.slug] }}</div>
              <div v-else class="markdown-body" v-html="skillContent[skill.slug]" />
            </div>
          </li>
        </ul>
      </section>

    </main>
  </div>
</template>

<style scoped>
/* ── Layout ─────────────────────────────────────────────────── */
.faq-layout {
  width: 100%;
  max-width: 72rem;
  margin: 0 auto;
  display: grid;
  grid-template-columns: 14rem minmax(0, 1fr);
  gap: 1.5rem;
  align-items: start;
}

/* ── Sidebar ─────────────────────────────────────────────────── */
.sidebar {
  position: sticky;
  top: 1.25rem;
  align-self: start;
  border: 1px solid var(--border, rgba(0, 0, 0, 0.08));
  border-radius: 14px;
  padding: 1.1rem 1rem;
  background: var(--bg, #fafafa);
}

@media (prefers-color-scheme: dark) {
  .sidebar { background: rgba(255, 255, 255, 0.03); }
}

.sidebar-header { margin-bottom: 1.1rem; }

.sidebar-title {
  margin: 0 0 0.25rem;
  font-size: 1.1rem;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.sidebar-desc {
  margin: 0;
  font-size: 0.775rem;
  color: var(--muted, #5c5c5c);
  line-height: 1.4;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.sidebar-label {
  display: block;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--muted, #5c5c5c);
  margin-bottom: 0.35rem;
}

.sidebar-link {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  text-decoration: none;
  color: inherit;
  border-radius: 8px;
  padding: 0.42rem 0.6rem;
  font-size: 0.875rem;
  transition: background 0.12s;
}

.sidebar-link:hover { background: rgba(0, 0, 0, 0.05); }

@media (prefers-color-scheme: dark) {
  .sidebar-link:hover { background: rgba(255, 255, 255, 0.07); }
}

.icon { font-size: 0.8rem; opacity: 0.65; flex-shrink: 0; }

/* ── Content ─────────────────────────────────────────────────── */
.content {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

/* ── Card ────────────────────────────────────────────────────── */
.card {
  border: 1px solid var(--border, rgba(0, 0, 0, 0.08));
  border-radius: 14px;
  overflow: hidden;
}

.card-header {
  padding: 1.1rem 1.35rem 1rem;
  border-bottom: 1px solid var(--border, rgba(0, 0, 0, 0.06));
  background: rgba(0, 0, 0, 0.015);
}

@media (prefers-color-scheme: dark) {
  .card-header { background: rgba(255, 255, 255, 0.025); }
}

.card-title {
  margin: 0 0 0.35rem;
  font-size: 1rem;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.card-desc {
  margin: 0;
  font-size: 0.875rem;
  color: var(--muted, #5c5c5c);
  line-height: 1.55;
}

.card-body { padding: 1.25rem 1.35rem; }

/* ── Doc list ────────────────────────────────────────────────── */
.doc-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  padding: 2.5rem 1rem;
  color: var(--muted, #5c5c5c);
  font-size: 0.875rem;
}

.doc-empty-icon { font-size: 2rem; opacity: 0.4; }

.doc-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.doc-item {
  border-bottom: 1px solid var(--border, rgba(0, 0, 0, 0.06));
}

.doc-item:last-child { border-bottom: none; }

.doc-row {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.9rem 1.35rem;
  flex-wrap: wrap;
}

.doc-meta {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.doc-title {
  font-size: 0.9375rem;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.doc-url {
  font-size: 0.775rem;
  font-family: "SF Mono", ui-monospace, Consolas, monospace;
  color: var(--muted, #5c5c5c);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.doc-actions {
  display: flex;
  gap: 0.4rem;
  flex-shrink: 0;
  flex-wrap: wrap;
}

/* Shared action button base */
.action-btn {
  font: inherit;
  font-size: 0.8rem;
  font-weight: 500;
  padding: 0.32rem 0.75rem;
  border-radius: 7px;
  border: 1px solid var(--border, rgba(0, 0, 0, 0.1));
  background: transparent;
  color: inherit;
  cursor: pointer;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  white-space: nowrap;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
}

.action-btn:hover { background: rgba(0, 0, 0, 0.05); }

@media (prefers-color-scheme: dark) {
  .action-btn:hover { background: rgba(255, 255, 255, 0.07); }
}

.copy-btn.copied {
  border-color: #15803d;
  color: #15803d;
  background: rgba(21, 128, 61, 0.06);
}

.read-btn.active {
  background: rgba(0, 0, 0, 0.06);
  border-color: rgba(0, 0, 0, 0.15);
}

@media (prefers-color-scheme: dark) {
  .read-btn.active {
    background: rgba(255, 255, 255, 0.1);
    border-color: rgba(255, 255, 255, 0.18);
  }
}

/* ── Inline reader ───────────────────────────────────────────── */
.doc-reader {
  padding: 1rem 1.35rem 1.25rem;
  border-top: 1px solid var(--border, rgba(0, 0, 0, 0.06));
  background: rgba(0, 0, 0, 0.015);
}

@media (prefers-color-scheme: dark) {
  .doc-reader { background: rgba(255, 255, 255, 0.02); }
}

.reader-status {
  font-size: 0.875rem;
  color: var(--muted, #5c5c5c);
}

.reader-status.err { color: #b91c1c; }

/* ── Markdown body ───────────────────────────────────────────── */
.markdown-body {
  font-size: 0.9375rem;
  line-height: 1.7;
  color: inherit;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 1.4rem 0 0.55rem;
  font-weight: 600;
  line-height: 1.3;
}

.markdown-body :deep(h1) { font-size: 1.3rem; }
.markdown-body :deep(h2) { font-size: 1.1rem; }
.markdown-body :deep(h3) { font-size: 1rem; }

.markdown-body :deep(p) { margin: 0 0 0.8rem; }

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0 0 0.8rem;
  padding-left: 1.4rem;
}

.markdown-body :deep(li) { margin-bottom: 0.35rem; }

.markdown-body :deep(code) {
  font-size: 0.8125rem;
  font-family: "SF Mono", ui-monospace, Consolas, monospace;
  padding: 0.1em 0.38em;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.06);
}

@media (prefers-color-scheme: dark) {
  .markdown-body :deep(code) { background: rgba(255, 255, 255, 0.1); }
}

.markdown-body :deep(pre) {
  margin: 0.5rem 0 0.9rem;
  padding: 0.8rem 1rem;
  border-radius: 8px;
  border: 1px solid var(--border, rgba(0, 0, 0, 0.08));
  background: rgba(0, 0, 0, 0.03);
  overflow: auto;
  font-size: 0.8125rem;
  line-height: 1.55;
}

@media (prefers-color-scheme: dark) {
  .markdown-body :deep(pre) { background: rgba(255, 255, 255, 0.05); }
}

.markdown-body :deep(pre code) { background: none; padding: 0; }

.markdown-body :deep(blockquote) {
  margin: 0.75rem 0;
  padding: 0.5rem 1rem;
  border-left: 3px solid var(--border, rgba(0, 0, 0, 0.18));
  color: var(--muted, #5c5c5c);
}

.markdown-body :deep(hr) {
  border: none;
  border-top: 1px solid var(--border, rgba(0, 0, 0, 0.08));
  margin: 1.1rem 0;
}

.markdown-body :deep(a) {
  color: inherit;
  text-decoration: underline;
  opacity: 0.8;
}

.markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 0.75rem 0;
  font-size: 0.875rem;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid var(--border, rgba(0, 0, 0, 0.1));
  padding: 0.45rem 0.7rem;
  text-align: left;
}

.markdown-body :deep(th) {
  background: rgba(0, 0, 0, 0.04);
  font-weight: 600;
}

@media (prefers-color-scheme: dark) {
  .markdown-body :deep(th) { background: rgba(255, 255, 255, 0.06); }
}

/* ── Form ────────────────────────────────────────────────────── */
.form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.label {
  font-size: 0.8125rem;
  font-weight: 600;
}

.input,
.textarea {
  font: inherit;
  font-size: 0.9rem;
  padding: 0.55rem 0.7rem;
  border-radius: 8px;
  border: 1px solid var(--border, rgba(0, 0, 0, 0.12));
  background: var(--bg, #fafafa);
  color: inherit;
  transition: border-color 0.15s, box-shadow 0.15s;
  outline: none;
}

.input:focus,
.textarea:focus {
  border-color: var(--fg, #1a1a1a);
  box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.06);
}

@media (prefers-color-scheme: dark) {
  .input:focus,
  .textarea:focus { box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.08); }
}

.textarea { resize: vertical; min-height: 6rem; line-height: 1.55; }

.form-footer {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  align-items: flex-start;
}

.submit-btn {
  font: inherit;
  font-size: 0.875rem;
  font-weight: 600;
  padding: 0.55rem 1.3rem;
  border-radius: 8px;
  border: none;
  background: var(--fg, #1a1a1a);
  color: var(--bg, #fafafa);
  cursor: pointer;
  transition: opacity 0.15s;
}

.submit-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.submit-btn:not(:disabled):hover { opacity: 0.82; }

@media (prefers-color-scheme: dark) {
  .submit-btn { background: #e8e8e8; color: #121212; }
}

.status { margin: 0; font-size: 0.875rem; }
.status.ok { color: #15803d; }
.status.err { color: #b91c1c; }

.note {
  margin: 1.1rem 0 0;
  padding: 0.7rem 0.9rem;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.03);
  border: 1px solid var(--border, rgba(0, 0, 0, 0.06));
  font-size: 0.8125rem;
  color: var(--muted, #5c5c5c);
  line-height: 1.55;
}

@media (prefers-color-scheme: dark) {
  .note { background: rgba(255, 255, 255, 0.04); }
}

/* ── Inline code (template-level) ────────────────────────────── */
code {
  font-size: 0.8125rem;
  font-family: "SF Mono", ui-monospace, Consolas, monospace;
  padding: 0.1em 0.35em;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.06);
}

@media (prefers-color-scheme: dark) {
  code { background: rgba(255, 255, 255, 0.1); }
}

/* ── Steps ───────────────────────────────────────────────────── */
.steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.step {
  display: flex;
  gap: 0.85rem;
  align-items: flex-start;
}

.step-num {
  flex-shrink: 0;
  width: 1.6rem;
  height: 1.6rem;
  border-radius: 50%;
  border: 1.5px solid var(--border, rgba(0, 0, 0, 0.12));
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--muted, #5c5c5c);
  margin-top: 0.05rem;
}

.step-body {
  font-size: 0.9375rem;
  line-height: 1.6;
  flex: 1;
  min-width: 0;
}

.code-block {
  margin: 0.55rem 0 0;
  padding: 0.65rem 0.85rem;
  border-radius: 8px;
  font-size: 0.8125rem;
  font-family: "SF Mono", ui-monospace, Consolas, monospace;
  line-height: 1.5;
  overflow: auto;
  border: 1px solid var(--border, rgba(0, 0, 0, 0.1));
  background: rgba(0, 0, 0, 0.03);
  white-space: pre;
}

@media (prefers-color-scheme: dark) {
  .code-block { background: rgba(255, 255, 255, 0.05); }
}

/* ── Responsive ──────────────────────────────────────────────── */
@media (max-width: 860px) {
  .faq-layout {
    grid-template-columns: 1fr;
  }

  .sidebar {
    position: static;
  }

  .doc-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.65rem;
  }

  .doc-url {
    max-width: 100%;
  }
}
</style>
