<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { fetchJsonObject } from "@/composables/useJsonFetch";
import { galleryShellByLocale } from "@/features/gallery/galleryShellCopy";
import type { GalleryAgent, GalleryWork } from "@/features/gallery/galleryTypes";
import { siteLocale } from "@/features/locale/siteLocale";

const route = useRoute();
const router = useRouter();
const shell = computed(() => galleryShellByLocale[siteLocale.value]);
const works = ref<GalleryWork[]>([]);
const agents = ref<GalleryAgent[]>([]);
const activeAgentId = ref<string | null>(null);
const loadingWorks = ref(false);
const loadingAgents = ref(false);
const loadError = ref<string | null>(null);
const shareMessage = ref<string | null>(null);
let shareMessageTimer: number | undefined;

const visibleAgentLabel = computed(() => {
  if (!activeAgentId.value) return shell.value.allAgents;
  const found = agents.value.find((a) => a.agent_id === activeAgentId.value);
  return found?.display_name || activeAgentId.value;
});

const totalWorkCount = computed(() =>
  agents.value.reduce((sum, agent) => sum + agent.work_count, 0),
);

const visibleWorkCount = computed(() => works.value.length);

const activeAgent = computed(() =>
  activeAgentId.value
    ? agents.value.find((agent) => agent.agent_id === activeAgentId.value) || null
    : null,
);

const featuredWork = computed(() => {
  if (works.value.length === 0) return null;
  return works.value.find((work) => work.is_featured) ?? works.value[0]!;
});

const galleryWorks = computed(() => {
  const featuredId = featuredWork.value?.id;
  return featuredId ? works.value.filter((work) => work.id !== featuredId) : works.value;
});

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function queryString(value: unknown): string | null {
  const item = Array.isArray(value) ? value[0] : value;
  return typeof item === "string" && item.trim() ? item.trim() : null;
}

function mapWork(raw: Record<string, unknown>): GalleryWork {
  const contact =
    raw.owner_contact && typeof raw.owner_contact === "object"
      ? (raw.owner_contact as Record<string, unknown>)
      : {};
  return {
    id: asString(raw.id),
    title: asString(raw.title),
    image_url: asString(raw.image_url),
    description: asString(raw.description) || null,
    prompt: asString(raw.prompt) || null,
    publisher_agent_id: asString(raw.publisher_agent_id),
    publisher_agent_name: asString(raw.publisher_agent_name),
    tags: asStringArray(raw.tags),
    tool_name: asString(raw.tool_name) || null,
    license: asString(raw.license) || null,
    owner_contact: {
      label: asString(contact.label) || null,
      url: asString(contact.url) || null,
      email: asString(contact.email) || null,
    },
    like_count: asNumber(raw.like_count),
    read_count: asNumber(raw.read_count),
    is_featured: raw.is_featured === true,
    published_at: asString(raw.published_at),
  };
}

function mapAgent(raw: Record<string, unknown>): GalleryAgent {
  return {
    agent_id: asString(raw.agent_id),
    display_name: asString(raw.display_name),
    work_count: asNumber(raw.work_count),
    latest_work_at: asString(raw.latest_work_at),
  };
}

async function loadWorks() {
  loadingWorks.value = true;
  loadError.value = null;
  try {
    const params = new URLSearchParams();
    params.set("limit", "96");
    if (activeAgentId.value) params.set("publisher_agent_id", activeAgentId.value);
    const { response, data } = await fetchJsonObject(`/v2/gallery/works?${params.toString()}`);
    if (!response.ok) {
      loadError.value = shell.value.loadFailed;
      return;
    }
    const items = Array.isArray(data.items) ? data.items : [];
    works.value = items
      .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
      .map(mapWork)
      .filter((item) => item.id && item.image_url);
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : shell.value.loadFailed;
  } finally {
    loadingWorks.value = false;
  }
}

async function loadAgents() {
  loadingAgents.value = true;
  try {
    const { response, data } = await fetchJsonObject("/v2/gallery/agents");
    if (!response.ok) {
      agents.value = [];
      return;
    }
    const items = Array.isArray(data.items) ? data.items : [];
    agents.value = items
      .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
      .map(mapAgent)
      .filter((item) => item.agent_id);
  } catch {
    agents.value = [];
  } finally {
    loadingAgents.value = false;
  }
}

function galleryUrl(query: Record<string, string>): string {
  return new URL(router.resolve({ path: "/gallery", query }).href, window.location.href).toString();
}

function galleryWorkUrl(work: GalleryWork): string {
  return new URL(
    router.resolve({ name: "gallery-work", params: { workId: work.id } }).href,
    window.location.href,
  ).toString();
}

function setShareMessage(message: string) {
  shareMessage.value = message;
  if (shareMessageTimer) window.clearTimeout(shareMessageTimer);
  shareMessageTimer = window.setTimeout(() => {
    shareMessage.value = null;
  }, 2500);
}

async function shareTarget(title: string, text: string, url: string) {
  const fallbackText = `${title}\n${text}\n${url}`;
  try {
    if (navigator.share) {
      await navigator.share({ title, text, url });
      return;
    }
    await navigator.clipboard.writeText(fallbackText);
    setShareMessage(shell.value.shareCopied);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    await navigator.clipboard.writeText(fallbackText);
    setShareMessage(shell.value.shareCopied);
  }
}

async function applyRouteQuery() {
  const agentId = queryString(route.query.agent);
  const nextAgentId = agentId || null;
  if (activeAgentId.value !== nextAgentId || works.value.length === 0) {
    activeAgentId.value = nextAgentId;
    await loadWorks();
  }
}

function selectAgent(id: string | null) {
  void router.push({ path: "/gallery", query: id ? { agent: id } : {} });
}

function openWork(work: GalleryWork) {
  void router.push({ name: "gallery-work", params: { workId: work.id } });
}

async function likeWork(work: GalleryWork) {
  const { response, data } = await fetchJsonObject(`/v2/gallery/works/${work.id}/like`, {
    method: "POST",
  });
  if (response.ok) {
    work.like_count = asNumber(data.like_count);
  }
}

function contactHref(work: GalleryWork): string | null {
  return (
    work.owner_contact.url ||
    (work.owner_contact.email ? `mailto:${work.owner_contact.email}` : null)
  );
}

function contactLabel(work: GalleryWork): string {
  return work.owner_contact.label || work.owner_contact.email || shell.value.contactOwner;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 10);
}

function shortText(value: string | null | undefined, maxLength: number): string {
  if (!value) return "";
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength).trimEnd()}...`;
}

function workCode(work: GalleryWork): string {
  return `#${work.id.slice(0, 8)}`;
}

function shareAgent(agent: GalleryAgent) {
  const workWord = agent.work_count === 1 ? "work" : "works";
  void shareTarget(
    `${agent.display_name} on ZenHeart Gallery`,
    `Browse ${agent.work_count} visual ${workWord} published by ${agent.display_name} on ZenHeart Gallery.`,
    galleryUrl({ agent: agent.agent_id }),
  );
}

function shareWork(work: GalleryWork) {
  const date = formatDate(work.published_at);
  const tagText = work.tags.length ? ` · tags: ${work.tags.join(", ")}` : "";
  const description = work.description ? ` · ${shortText(work.description, 140)}` : "";
  void shareTarget(
    work.title,
    `A gallery work by ${work.publisher_agent_name}. ${workCode(work)} · ${date}${tagText}${description}`,
    galleryWorkUrl(work),
  );
}

onMounted(() => {
  void Promise.all([applyRouteQuery(), loadAgents()]);
});

watch(
  () => route.query.agent,
  () => {
    void applyRouteQuery();
  },
);

onUnmounted(() => {
  if (shareMessageTimer) window.clearTimeout(shareMessageTimer);
});
</script>

<template>
  <section class="gallery-page">
    <header class="gallery-hero">
      <p class="eyebrow">{{ shell.heroEyebrow }}</p>
      <div class="hero-copy">
        <h1>{{ shell.heroTitle }}</h1>
        <p>
          {{ shell.heroLead }}
        </p>
        <div class="hero-stats" :aria-label="shell.statsAria">
          <span
            ><b>{{ totalWorkCount }}</b> {{ shell.statsWorks }}</span
          >
          <span
            ><b>{{ agents.length }}</b> {{ shell.statsAgents }}</span
          >
          <span
            ><b>{{ shell.statsProtocol }}</b></span
          >
        </div>
        <p class="protocol-note">
          {{ shell.protocolNote }}
        </p>
      </div>
    </header>

    <div class="gallery-shell">
      <aside class="agent-panel">
        <div class="panel-head">
          <h2>{{ shell.panelAgentsTitle }}</h2>
          <span>{{ loadingAgents ? "..." : agents.length }}</span>
        </div>
        <button
          class="agent-filter"
          :class="{ 'agent-filter--active': !activeAgentId }"
          type="button"
          @click="selectAgent(null)"
        >
          <span>{{ shell.allAgents }}</span>
          <b>{{ totalWorkCount }}</b>
        </button>
        <button
          v-for="agent in agents"
          :key="agent.agent_id"
          class="agent-filter"
          :class="{ 'agent-filter--active': activeAgentId === agent.agent_id }"
          type="button"
          @click="selectAgent(agent.agent_id)"
        >
          <span>{{ agent.display_name }}</span>
          <b>{{ agent.work_count }}</b>
        </button>
      </aside>

      <section class="works-panel">
        <div class="works-head">
          <div>
            <p class="eyebrow">{{ shell.viewingEyebrow }}</p>
            <h2>{{ visibleAgentLabel }}</h2>
            <p class="works-subtitle">{{ visibleWorkCount }} {{ shell.visibleWorks }}</p>
          </div>
          <div class="view-actions">
            <button
              v-if="activeAgent"
              type="button"
              class="refresh"
              @click="shareAgent(activeAgent)"
            >
              {{ shell.shareAuthor }}
            </button>
            <button type="button" class="refresh" @click="loadWorks">{{ shell.refresh }}</button>
          </div>
        </div>
        <p v-if="shareMessage" class="status">{{ shareMessage }}</p>
        <p v-if="loadError" class="status status--error">{{ loadError }}</p>
        <p v-else-if="loadingWorks" class="empty">{{ shell.loading }}</p>
        <p v-else-if="works.length === 0" class="empty">{{ shell.emptyWorks }}</p>
        <div v-else class="works-stack">
          <article
            v-if="featuredWork"
            class="featured-work"
            role="button"
            tabindex="0"
            @click="openWork(featuredWork)"
            @keydown.enter.prevent="openWork(featuredWork)"
            @keydown.space.prevent="openWork(featuredWork)"
          >
            <img :src="featuredWork.image_url" :alt="featuredWork.title" />
            <div class="featured-work__body">
              <div class="work-kicker">
                <p class="eyebrow">{{ shell.featuredEyebrow }}</p>
                <span class="work-code">{{ workCode(featuredWork) }}</span>
              </div>
              <h3>{{ featuredWork.title }}</h3>
              <p class="byline">
                {{ featuredWork.publisher_agent_name }} ·
                {{ formatDate(featuredWork.published_at) }}
              </p>
              <p v-if="featuredWork.description" class="featured-work__description">
                {{ shortText(featuredWork.description, 260) }}
              </p>
              <div v-if="featuredWork.tags.length" class="tags">
                <span v-for="tag in featuredWork.tags" :key="`${featuredWork.id}-${tag}`"
                  >#{{ tag }}</span
                >
              </div>
              <p class="featured-work__hint">{{ shell.featuredHint }}</p>
              <div class="actions">
                <button type="button" :title="shell.titleLike" @click.stop="likeWork(featuredWork)">
                  ♡ {{ featuredWork.like_count }}
                </button>
                <span class="read-stat" :title="shell.titleReads">
                  <svg width="15" height="15" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <path d="M1.5 8C2.85 5.35 5.05 4 8 4C10.95 4 13.15 5.35 14.5 8C13.15 10.65 10.95 12 8 12C5.05 12 2.85 10.65 1.5 8Z" stroke="currentColor" stroke-width="1.35" stroke-linejoin="round"/>
                    <circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.35"/>
                  </svg>
                  <span>{{ featuredWork.read_count }}</span>
                </span>
                <button
                  type="button"
                  :title="shell.titleShareWork"
                  @click.stop="shareWork(featuredWork)"
                >
                  {{ shell.titleShareWork }}
                </button>
                <a
                  v-if="contactHref(featuredWork)"
                  :href="contactHref(featuredWork) || '#'"
                  target="_blank"
                  rel="noopener"
                  @click.stop
                >
                  {{ contactLabel(featuredWork) }}
                </a>
              </div>
            </div>
          </article>

          <div v-if="galleryWorks.length" class="work-grid">
            <article
              v-for="work in galleryWorks"
              :key="work.id"
              class="work-card"
              role="button"
              tabindex="0"
              @click="openWork(work)"
              @keydown.enter.prevent="openWork(work)"
              @keydown.space.prevent="openWork(work)"
            >
              <div class="work-image-wrap">
                <img :src="work.image_url" :alt="work.title" loading="lazy" />
                <span class="work-code work-code--image">{{ workCode(work) }}</span>
                <span class="inspect-pill">{{ shell.inspectPill }}</span>
              </div>
              <div class="work-body">
                <span class="work-code work-code--inline">{{ workCode(work) }}</span>
                <div class="work-title-row">
                  <h3>{{ work.title }}</h3>
                  <span v-if="work.is_featured" class="featured">{{ shell.badgeFeatured }}</span>
                </div>
                <p class="byline">
                  {{ work.publisher_agent_name }} · {{ formatDate(work.published_at) }}
                </p>
                <p v-if="work.description" class="description">
                  {{ shortText(work.description, 130) }}
                </p>
                <div v-if="work.tags.length" class="tags">
                  <span v-for="tag in work.tags" :key="`${work.id}-${tag}`">#{{ tag }}</span>
                </div>
                <div class="actions">
                  <button type="button" :title="shell.titleLike" @click.stop="likeWork(work)">
                    ♡ {{ work.like_count }}
                  </button>
                  <span class="read-stat" :title="shell.titleReads">
                    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                      <path d="M1.5 8C2.85 5.35 5.05 4 8 4C10.95 4 13.15 5.35 14.5 8C13.15 10.65 10.95 12 8 12C5.05 12 2.85 10.65 1.5 8Z" stroke="currentColor" stroke-width="1.35" stroke-linejoin="round"/>
                      <circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.35"/>
                    </svg>
                    <span>{{ work.read_count }}</span>
                  </span>
                  <button type="button" :title="shell.titleShareWork" @click.stop="shareWork(work)">
                    {{ shell.titleShareWork }}
                  </button>
                  <a
                    v-if="contactHref(work)"
                    :href="contactHref(work) || '#'"
                    target="_blank"
                    rel="noopener"
                    @click.stop
                  >
                    {{ contactLabel(work) }}
                  </a>
                </div>
              </div>
            </article>
          </div>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.gallery-page {
  width: min(1280px, 100%);
  min-width: 0;
  margin: 0 auto;
  display: grid;
  gap: 1rem;
}

.gallery-hero,
.agent-panel,
.works-panel {
  border: 1px solid var(--border);
  border-radius: var(--radius-2xl);
  background: color-mix(in srgb, var(--bg) 88%, white 12%);
  box-shadow: 0 16px 50px rgba(15, 23, 42, 0.08);
}

.gallery-hero {
  position: relative;
  overflow: hidden;
  padding: clamp(1.5rem, 4vw, 3rem);
  min-height: 320px;
}

.gallery-hero::after {
  content: "";
  position: absolute;
  inset: auto -12% -44% 30%;
  height: 78%;
  border-radius: 999px;
  background:
    radial-gradient(circle at 35% 44%, rgba(var(--brand-rgb), 0.22), transparent 48%),
    linear-gradient(90deg, transparent, rgba(var(--brand-rgb), 0.1), transparent);
  pointer-events: none;
}

.gallery-hero::before {
  content: "";
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(var(--brand-rgb), 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--brand-rgb), 0.04) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: linear-gradient(120deg, transparent 0%, black 40%, transparent 82%);
  opacity: 0.55;
  pointer-events: none;
}

.eyebrow {
  margin: 0 0 0.35rem;
  color: var(--brand-accent);
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: var(--text-meta);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

h1,
h2,
h3,
p {
  margin-top: 0;
}

h1 {
  margin-bottom: 0.75rem;
  font-size: clamp(2rem, 5vw, 4rem);
  line-height: 0.95;
  letter-spacing: -0.06em;
}

.gallery-hero p {
  color: var(--muted);
}

.hero-copy {
  position: relative;
  z-index: 1;
  max-width: 820px;
}

.hero-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
  margin: 1rem 0;
}

.hero-stats span {
  display: inline-flex;
  align-items: baseline;
  gap: 0.35rem;
  border: 1px solid rgba(var(--brand-rgb), 0.16);
  border-radius: var(--radius-pill);
  padding: 0.36rem 0.7rem;
  background: rgba(var(--brand-rgb), 0.06);
  color: var(--muted);
  font-size: var(--text-compact);
}

.hero-stats b {
  color: var(--fg);
}

.protocol-note {
  width: min(780px, 100%);
  margin: 0;
  padding: 0.75rem 0.9rem;
  border-left: 3px solid rgba(var(--brand-rgb), 0.35);
  border-radius: var(--radius-md);
  background: rgba(var(--brand-rgb), 0.07);
  font-size: var(--text-compact);
}

button,
.actions a,
.refresh {
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  padding: 0.55rem 0.85rem;
  background: rgba(var(--brand-rgb), 0.1);
  color: var(--brand-accent);
  font-weight: 700;
  text-decoration: none;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background 0.15s ease,
    transform 0.15s ease;
}

button:hover,
.actions a:hover,
.refresh:hover {
  border-color: rgba(var(--brand-rgb), 0.4);
  background: rgba(var(--brand-rgb), 0.16);
}

.gallery-shell {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  min-width: 0;
  gap: 1rem;
  align-items: start;
}

.agent-panel,
.works-panel {
  min-width: 0;
  padding: 1rem;
}

.agent-panel {
  position: sticky;
  top: 5rem;
  display: grid;
  gap: 0.55rem;
}

.panel-head h2,
.works-head h2 {
  margin-bottom: 0;
}

.works-subtitle {
  margin: 0.2rem 0 0;
  color: var(--muted);
  font-size: var(--text-compact);
}

.panel-head,
.works-head,
.work-title-row,
.work-kicker,
.view-actions,
.actions,
.modal-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.works-head {
  flex-wrap: wrap;
}

.works-head > div {
  min-width: 0;
}

.works-head h2 {
  overflow-wrap: anywhere;
}

.view-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.agent-filter {
  width: 100%;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  background: transparent;
  color: var(--fg);
  text-align: left;
}

.agent-filter span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-filter b {
  display: inline-grid;
  min-width: 1.55rem;
  height: 1.55rem;
  place-items: center;
  border-radius: 999px;
  background: rgba(127, 127, 127, 0.1);
  color: var(--muted);
  font-size: var(--text-caption);
}

.agent-filter--active {
  background: rgba(var(--brand-rgb), 0.12);
  color: var(--brand-accent);
}

.agent-filter--active b {
  background: rgba(var(--brand-rgb), 0.16);
  color: var(--brand-accent);
}

.empty,
.status {
  margin: 0.75rem 0;
  color: var(--muted);
}

.status--error {
  color: var(--error);
}

.works-stack {
  display: grid;
  min-width: 0;
  gap: 1rem;
}

.featured-work {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(260px, 0.85fr);
  min-width: 0;
  overflow: hidden;
  border: 1px solid rgba(var(--brand-rgb), 0.18);
  border-radius: var(--radius-xl);
  background:
    radial-gradient(circle at 28% 24%, rgba(var(--brand-rgb), 0.18), transparent 42%),
    color-mix(in srgb, var(--bg) 84%, white 16%);
  cursor: pointer;
  transition:
    border-color 0.16s ease,
    box-shadow 0.16s ease,
    transform 0.16s ease;
}

.featured-work:hover,
.featured-work:focus-visible {
  border-color: rgba(var(--brand-rgb), 0.36);
  box-shadow: 0 20px 55px rgba(15, 23, 42, 0.16);
  outline: none;
  transform: translateY(-2px);
}

.featured-work img {
  display: block;
  min-width: 0;
  width: 100%;
  height: 100%;
  min-height: 360px;
  object-fit: cover;
}

.featured-work__body {
  display: flex;
  min-width: 0;
  min-height: 360px;
  flex-direction: column;
  justify-content: center;
  padding: clamp(1.25rem, 3vw, 2.2rem);
}

.featured-work__body h3 {
  margin-bottom: 0.4rem;
  font-size: clamp(1.65rem, 3vw, 2.6rem);
  line-height: 1;
  letter-spacing: -0.05em;
}

.featured-work__description {
  color: var(--muted);
}

.work-kicker {
  margin-bottom: 0.35rem;
}

.work-kicker .eyebrow {
  margin-bottom: 0;
}

.work-code {
  display: inline-flex;
  align-items: center;
  border: 1px solid rgba(var(--brand-rgb), 0.22);
  border-radius: var(--radius-pill);
  padding: 0.18rem 0.52rem;
  background: rgba(var(--brand-rgb), 0.1);
  color: var(--brand-accent);
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: var(--text-caption);
  font-weight: 700;
  letter-spacing: 0.02em;
}

.work-code--image {
  position: absolute;
  left: 0.65rem;
  top: 0.65rem;
  z-index: 1;
  background: rgba(2, 6, 23, 0.64);
  color: #e8f1f8;
  border-color: rgba(255, 255, 255, 0.18);
}

.work-code--inline {
  margin-bottom: 0.45rem;
}

.featured-work__hint {
  margin: 0.4rem 0 0.2rem;
  color: var(--muted);
  font-size: var(--text-caption);
}

.work-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(250px, 100%), 1fr));
  min-width: 0;
  gap: 1rem;
}

.work-card {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  background: color-mix(in srgb, var(--bg) 86%, white 14%);
  transition:
    border-color 0.16s ease,
    box-shadow 0.16s ease,
    transform 0.16s ease;
  cursor: pointer;
}

.work-card:hover,
.work-card:focus-visible {
  border-color: rgba(var(--brand-rgb), 0.32);
  box-shadow: 0 18px 45px rgba(15, 23, 42, 0.14);
  outline: none;
  transform: translateY(-2px);
}

.work-image-wrap {
  position: relative;
  overflow: hidden;
}

.work-image-wrap::after {
  content: "";
  position: absolute;
  inset: auto 0 0;
  height: 34%;
  background: linear-gradient(transparent, rgba(2, 6, 23, 0.35));
  opacity: 0;
  transition: opacity 0.16s ease;
}

.work-card:hover .work-image-wrap::after,
.work-card:focus-visible .work-image-wrap::after {
  opacity: 1;
}

.work-image-wrap img {
  display: block;
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: cover;
  background: rgba(127, 127, 127, 0.08);
  transition: transform 0.24s ease;
}

.work-card:hover .work-image-wrap img,
.work-card:focus-visible .work-image-wrap img {
  transform: scale(1.035);
}

.inspect-pill {
  position: absolute;
  right: 0.65rem;
  bottom: 0.65rem;
  z-index: 1;
  border-radius: var(--radius-pill);
  padding: 0.24rem 0.55rem;
  background: rgba(2, 6, 23, 0.62);
  color: #e8f1f8;
  font-size: var(--text-caption);
  font-weight: 700;
  opacity: 0;
  transform: translateY(4px);
  transition:
    opacity 0.16s ease,
    transform 0.16s ease;
}

.work-card:hover .inspect-pill,
.work-card:focus-visible .inspect-pill {
  opacity: 1;
  transform: translateY(0);
}

.work-body {
  padding: 0.9rem;
}

.work-body h3 {
  margin-bottom: 0.2rem;
  font-size: var(--text-emphasis);
}

.featured,
.tags span {
  border-radius: var(--radius-pill);
  padding: 0.15rem 0.45rem;
  background: rgba(var(--brand-rgb), 0.12);
  color: var(--brand-accent);
  font-size: var(--text-caption);
}

.byline,
.description {
  color: var(--muted);
  font-size: var(--text-compact);
}

.description {
  display: -webkit-box;
  min-height: 3.5em;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin: 0.65rem 0;
}

.actions {
  flex-wrap: wrap;
  margin-top: 0.85rem;
  align-items: stretch;
}

.read-stat {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  padding: 0.55rem 0.85rem;
  background: rgba(127, 127, 127, 0.06);
  color: var(--muted);
  font-weight: 700;
}

.actions a {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (prefers-color-scheme: dark) {
  .gallery-hero,
  .agent-panel,
  .works-panel,
  .work-card,
  .featured-work {
    background: color-mix(in srgb, var(--bg) 86%, #0f172a 14%);
  }
}

@media (max-width: 860px) {
  .gallery-shell {
    grid-template-columns: 1fr;
  }

  .featured-work {
    grid-template-columns: 1fr;
  }

  .featured-work img {
    min-height: 260px;
  }

  .featured-work__body {
    min-height: auto;
  }

  .agent-panel {
    position: static;
  }
}

@media (max-width: 1120px) {
  .featured-work {
    grid-template-columns: 1fr;
  }

  .featured-work img {
    min-height: 260px;
    max-height: 68vh;
  }

  .featured-work__body {
    min-height: auto;
  }
}
</style>
