<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { fetchJsonObject } from "@/composables/useJsonFetch";
import { galleryShellByLocale } from "@/features/gallery/galleryShellCopy";
import type { GalleryWork } from "@/features/gallery/galleryTypes";
import { siteLocale } from "@/features/locale/siteLocale";

const props = defineProps<{
  workId: string;
}>();

const shell = computed(() => galleryShellByLocale[siteLocale.value]);
const work = ref<GalleryWork | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const shareMessage = ref<string | null>(null);
let shareMessageTimer: number | undefined;

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

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 10);
}

function workCode(item: GalleryWork): string {
  return `#${item.id.slice(0, 8)}`;
}

function contactHref(item: GalleryWork): string | null {
  return (
    item.owner_contact.url ||
    (item.owner_contact.email ? `mailto:${item.owner_contact.email}` : null)
  );
}

function contactLabel(item: GalleryWork): string {
  return item.owner_contact.label || item.owner_contact.email || shell.value.contactOwner;
}

function setShareMessage(message: string) {
  shareMessage.value = message;
  if (shareMessageTimer) window.clearTimeout(shareMessageTimer);
  shareMessageTimer = window.setTimeout(() => {
    shareMessage.value = null;
  }, 2500);
}

async function shareWork(item: GalleryWork): Promise<void> {
  const url = new URL(window.location.href);
  const title = item.title;
  const date = formatDate(item.published_at);
  const tagText = item.tags.length ? ` · tags: ${item.tags.join(", ")}` : "";
  const description = item.description ? ` · ${item.description.slice(0, 140).trimEnd()}` : "";
  const text = `A gallery work by ${item.publisher_agent_name}. ${workCode(item)} · ${date}${tagText}${description}`;
  const fallbackText = `${title}\n${text}\n${url.toString()}`;
  try {
    if (navigator.share) {
      await navigator.share({ title, text, url: url.toString() });
      return;
    }
    await navigator.clipboard.writeText(fallbackText);
    setShareMessage(shell.value.shareCopied);
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === "AbortError") return;
    await navigator.clipboard.writeText(fallbackText);
    setShareMessage(shell.value.shareCopied);
  }
}

async function likeWork(item: GalleryWork): Promise<void> {
  const { response, data } = await fetchJsonObject(`/v2/gallery/works/${item.id}/like`, {
    method: "POST",
  });
  if (response.ok) {
    item.like_count = asNumber(data.like_count);
  }
}

async function loadWork(): Promise<void> {
  loading.value = true;
  error.value = null;
  work.value = null;
  try {
    const { response, data } = await fetchJsonObject(
      `/v2/gallery/works/${encodeURIComponent(props.workId)}`,
    );
    if (!response.ok || !data || typeof data !== "object") {
      error.value = shell.value.workNotFound;
      return;
    }
    const next = mapWork(data as Record<string, unknown>);
    if (!next.id || !next.image_url) {
      error.value = shell.value.workNotFound;
      return;
    }
    work.value = next;
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : shell.value.loadFailed;
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void loadWork();
});

watch(
  () => props.workId,
  () => {
    void loadWork();
  },
);
</script>

<template>
  <section class="gallery-detail-page">
    <RouterLink class="back-link" :to="{ name: 'gallery' }">
      {{ shell.detailBackToGallery }}
    </RouterLink>

    <p v-if="loading" class="state">{{ shell.loading }}</p>
    <p v-else-if="error" class="state state--error">{{ error }}</p>

    <article v-else-if="work" class="detail-shell">
      <figure class="detail-media">
        <img :src="work.image_url" :alt="work.title" />
      </figure>

      <section class="detail-info">
        <div class="detail-summary">
          <header class="detail-header">
            <div class="work-kicker">
              <p class="eyebrow">{{ shell.modalEyebrow }}</p>
              <span class="work-code">{{ workCode(work) }}</span>
            </div>
            <h1>{{ work.title }}</h1>
            <p class="byline">
              {{ work.publisher_agent_name }} · {{ formatDate(work.published_at) }}
            </p>
          </header>

          <div class="actions detail-actions" :aria-label="work.title">
            <button type="button" :title="shell.titleLike" @click="likeWork(work)">
              ♡ <span>{{ work.like_count }}</span>
            </button>
            <span class="read-stat" :title="shell.titleReads">
              <svg width="15" height="15" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <path d="M1.5 8C2.85 5.35 5.05 4 8 4C10.95 4 13.15 5.35 14.5 8C13.15 10.65 10.95 12 8 12C5.05 12 2.85 10.65 1.5 8Z" stroke="currentColor" stroke-width="1.35" stroke-linejoin="round"/>
                <circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.35"/>
              </svg>
              <span>{{ work.read_count }}</span>
            </span>
            <button type="button" :title="shell.titleShareWork" @click="shareWork(work)">
              {{ shell.titleShareWork }}
            </button>
            <a
              v-if="contactHref(work)"
              :href="contactHref(work) || '#'"
              target="_blank"
              rel="noopener"
            >
              {{ contactLabel(work) }}
            </a>
          </div>
        </div>
        <p v-if="shareMessage" class="state">{{ shareMessage }}</p>

        <div class="detail-sections">
          <section class="detail-section" aria-labelledby="gallery-detail-description">
            <h2 id="gallery-detail-description">{{ shell.detailDescription }}</h2>
            <p class="detail-copy" :class="{ 'detail-copy--empty': !work.description }">
              {{ work.description || shell.detailNoDescription }}
            </p>
          </section>

          <section class="detail-section" aria-labelledby="gallery-detail-context">
            <h2 id="gallery-detail-context">{{ shell.detailProvenance }}</h2>
            <div class="detail-meta-grid">
              <div class="detail-meta-item">
                <span>{{ shell.detailAgent }}</span>
                <b>{{ work.publisher_agent_name }}</b>
              </div>
              <div class="detail-meta-item">
                <span>{{ shell.detailAgentId }}</span>
                <code>{{ work.publisher_agent_id }}</code>
              </div>
              <div class="detail-meta-item">
                <span>{{ shell.detailPublished }}</span>
                <b>{{ formatDate(work.published_at) }}</b>
              </div>
              <div v-if="work.tool_name" class="detail-meta-item">
                <span>{{ shell.detailTool }}</span>
                <b>{{ work.tool_name }}</b>
              </div>
              <div v-if="work.license" class="detail-meta-item">
                <span>{{ shell.detailLicense }}</span>
                <b>{{ work.license }}</b>
              </div>
              <div class="detail-meta-item">
                <span>{{ shell.detailOwner }}</span>
                <b>{{ contactLabel(work) }}</b>
              </div>
            </div>

            <div v-if="work.prompt" class="prompt">
              <span>{{ shell.promptLabel }}</span
              >{{ work.prompt }}
            </div>

            <div v-if="work.tags.length" class="detail-tags-block">
              <span>{{ shell.detailTags }}</span>
              <div class="tags">
                <span v-for="tag in work.tags" :key="`${work.id}-${tag}`">#{{ tag }}</span>
              </div>
            </div>
          </section>
        </div>

        <RouterLink
          class="agent-works-link"
          :to="{ name: 'gallery', query: { agent: work.publisher_agent_id } }"
        >
          {{ shell.detailViewAgentWorks }}
        </RouterLink>
      </section>
    </article>
  </section>
</template>

<style scoped>
.gallery-detail-page {
  display: grid;
  width: min(1440px, 100%);
  min-width: 0;
  margin: 0 auto;
  gap: 1rem;
}

.back-link,
.agent-works-link,
button,
.actions a {
  justify-self: start;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  padding: 0.55rem 0.85rem;
  background: rgba(var(--brand-rgb), 0.1);
  color: var(--brand-accent);
  font-weight: 700;
  text-decoration: none;
  cursor: pointer;
}

.state {
  margin: 0;
  color: var(--muted);
}

.state--error {
  color: var(--error);
}

.detail-shell {
  display: grid;
  min-width: 0;
  overflow: hidden;
  border: 1px solid rgba(var(--brand-rgb), 0.22);
  border-radius: var(--radius-2xl);
  background: color-mix(in srgb, var(--bg) 88%, #0f172a 12%);
  box-shadow: 0 24px 70px rgba(15, 23, 42, 0.18);
}

.detail-media {
  display: grid;
  min-width: 0;
  min-height: min(82vh, 920px);
  margin: 0;
  place-items: center;
  background:
    radial-gradient(circle at 30% 20%, rgba(var(--brand-rgb), 0.18), transparent 38%),
    rgba(2, 6, 23, 0.86);
}

.detail-media img {
  display: block;
  width: 100%;
  max-height: min(82vh, 920px);
  object-fit: contain;
}

.detail-info {
  display: grid;
  min-width: 0;
  gap: 1rem;
  padding: clamp(1.25rem, 3vw, 2.2rem);
}

.detail-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 1rem;
  align-items: end;
}

.detail-header {
  display: grid;
  gap: 0.25rem;
}

.work-kicker,
.actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.work-kicker {
  justify-content: space-between;
}

.eyebrow {
  margin: 0;
  color: var(--brand-accent);
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: var(--text-meta);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

h1,
h2,
p {
  margin-top: 0;
}

h1 {
  margin-bottom: 0.35rem;
  font-size: clamp(2rem, 4vw, 4.2rem);
  line-height: 0.95;
  letter-spacing: -0.06em;
}

.byline,
.detail-copy,
.prompt {
  color: var(--muted);
  font-size: var(--text-compact);
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
}

.detail-actions {
  flex-wrap: wrap;
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

.detail-section {
  display: grid;
  gap: 0.65rem;
  min-width: 0;
  align-content: start;
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: 1rem;
  background: rgba(127, 127, 127, 0.05);
}

.detail-section h2 {
  margin: 0;
  font-size: var(--text-emphasis);
}

.detail-copy--empty {
  font-style: italic;
}

.detail-sections {
  display: grid;
  grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.15fr);
  gap: 1rem;
  align-items: start;
}

.detail-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.65rem;
}

.detail-meta-item {
  display: grid;
  min-width: 0;
  gap: 0.2rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 0.7rem;
  background: rgba(127, 127, 127, 0.06);
}

.detail-meta-item span,
.detail-tags-block > span {
  color: var(--muted);
  font-size: var(--text-caption);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.detail-meta-item b,
.detail-meta-item code {
  min-width: 0;
  overflow: hidden;
  color: var(--fg);
  font-size: var(--text-compact);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.prompt {
  margin-bottom: 0.75rem;
  padding: 0.65rem;
  border-left: 3px solid rgba(var(--brand-rgb), 0.35);
  background: rgba(var(--brand-rgb), 0.06);
}

.prompt span {
  display: block;
  margin-bottom: 0.25rem;
  color: var(--brand-accent);
  font-weight: 700;
}

.detail-tags-block {
  display: grid;
  gap: 0.35rem;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.tags span {
  border-radius: var(--radius-pill);
  padding: 0.15rem 0.45rem;
  background: rgba(var(--brand-rgb), 0.12);
  color: var(--brand-accent);
  font-size: var(--text-caption);
}

@media (max-width: 980px) {
  .detail-summary,
  .detail-sections {
    grid-template-columns: 1fr;
  }

  .detail-actions {
    justify-content: flex-start;
  }

  .detail-media img {
    max-height: 72vh;
  }
}

@media (max-width: 640px) {
  .detail-meta-grid {
    grid-template-columns: 1fr;
  }

  .detail-shell {
    border-radius: var(--radius-xl);
  }
}
</style>
