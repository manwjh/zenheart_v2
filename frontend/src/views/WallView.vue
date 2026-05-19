<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import AgentFeatureIntro from "../components/AgentFeatureIntro.vue";
import { shellCommonByLocale } from "@/features/locale/shellCommon";
import { siteLocale } from "@/features/locale/siteLocale";
import { wallShellByLocale } from "@/features/wall/wallShellCopy";

type WallItem = {
  id: string;
  body: string;
  from_type: string;
  author_label: string;
  source_kind: "registered" | "browser" | "api" | "legacy";
  created_at: string;
};

/** Match server: anonymous wall allows one post per 60 minutes per IP (`PUBLIC_WALL_ANONYMOUS_COOLDOWN_SECONDS`). */
const WALL_COOLDOWN_MS = 60 * 60 * 1000;
const SUBMIT_DEBOUNCE_MS = 400;
const LS_LAST_POST = "zenheart_wall_last_post";
const WALL_MSG_PATH = "/v2/wall/messages";
/** Match FaqView: build env, then live page origin, else production default — always full `https?://host` for copy-paste. */
const WALL_URL_FALLBACK_ORIGIN = "https://zenheart.net";

const wallPublicOrigin = computed(() => {
  const fromEnv = (import.meta.env.VITE_PUBLIC_SITE_ORIGIN as string | undefined)?.trim();
  if (fromEnv) return fromEnv.replace(/\/$/, "");
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin.replace(/\/$/, "");
  }
  return WALL_URL_FALLBACK_ORIGIN;
});

const wallApiAbsUrl = computed(() => `${wallPublicOrigin.value}${WALL_MSG_PATH}`);

const messages = ref<WallItem[]>([]);
const maxChars = ref(20);
const input = ref("");
const loading = ref(false);
const posting = ref(false);
const loadError = ref<string | null>(null);
const postError = ref<string | null>(null);
const notice = ref<string | null>(null);
const noticeOpen = ref(false);
const lastSubmitAt = ref(0);

const wallUi = computed(() => wallShellByLocale[siteLocale.value]);
const commonShell = computed(() => shellCommonByLocale[siteLocale.value]);
const composePlaceholderText = computed(() =>
  wallUi.value.composePlaceholder.replace("{max}", String(maxChars.value)),
);

/** Human-facing post-ack: split so https URLs become clickable. */
type NoticeSegment = { text: string; href?: string };

function _trimUrlTerminalPunc(url: string): string {
  let x = url;
  while (x.length > 0) {
    const c = x[x.length - 1]!;
    if (")],.;!?:\u201d\uff09".includes(c)) {
      x = x.slice(0, -1);
    } else {
      break;
    }
  }
  return x;
}

function linkifyWallNoticeText(raw: string): NoticeSegment[] {
  if (!raw) return [];
  const re = /https?:\/\/[^\s<]+/g;
  const out: NoticeSegment[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(raw)) !== null) {
    const i = m.index;
    if (i > last) {
      out.push({ text: raw.slice(last, i) });
    }
    const full = m[0]!;
    const href = _trimUrlTerminalPunc(full);
    if (href.length > 0) {
      out.push({ text: href, href });
    } else {
      out.push({ text: full });
    }
    const delta = full.length;
    last = i + delta;
  }
  if (last < raw.length) {
    out.push({ text: raw.slice(last) });
  }
  return out;
}

const noticeSegments = computed(() => linkifyWallNoticeText(notice.value ?? ""));

async function load() {
  loading.value = true;
  loadError.value = null;
  try {
    const res = await fetch(WALL_MSG_PATH);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      loadError.value = wallUi.value.failedLoad;
      return;
    }
    maxChars.value = typeof data.max_chars === "number" ? data.max_chars : 20;
    const raw = Array.isArray(data.messages) ? data.messages : [];
    messages.value = raw.map((m: Record<string, unknown>) => {
      const sk = m.source_kind;
      const source_kind: WallItem["source_kind"] =
        sk === "registered" || sk === "browser" || sk === "api" || sk === "legacy" ? sk : "legacy";
      return { ...m, source_kind } as WallItem;
    });
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : commonShell.value.networkError;
  } finally {
    loading.value = false;
  }
}

function closeNotice() {
  noticeOpen.value = false;
  notice.value = null;
}

function wallCooldownLeftMs(): number {
  const raw = localStorage.getItem(LS_LAST_POST);
  if (!raw) return 0;
  const t = parseInt(raw, 10);
  if (Number.isNaN(t)) return 0;
  return Math.max(0, WALL_COOLDOWN_MS - (Date.now() - t));
}

function formatWallWait(ms: number): string {
  const ui = wallUi.value;
  const sec = Math.ceil(ms / 1000);
  if (sec < 90) return ui.waitSeconds.replace("{n}", String(sec));
  const m = Math.ceil(sec / 60);
  if (m < 90) return ui.waitMinutes.replace("{n}", String(m));
  const h = Math.ceil(m / 60);
  return ui.waitHours.replace("{n}", String(h));
}

async function submit() {
  if (posting.value) return;
  const now = Date.now();
  if (now - lastSubmitAt.value < SUBMIT_DEBOUNCE_MS) return;
  lastSubmitAt.value = now;

  postError.value = null;
  const body = input.value.trim();
  if (!body) return;

  const cool = wallCooldownLeftMs();
  if (cool > 0) {
    postError.value = wallUi.value.waitBeforePost.replace("{wait}", formatWallWait(cool));
    return;
  }

  posting.value = true;
  try {
    const res = await fetch(WALL_MSG_PATH, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Wall-Client": "browser",
      },
      body: JSON.stringify({ body }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data as { detail?: string | unknown };
      const msg =
        typeof d.detail === "string" ? d.detail : commonShell.value.couldNotPost;
      postError.value =
        res.status === 429 ? msg || wallUi.value.cooldownDetail : typeof msg === "string" ? msg : String(msg);
      return;
    }
    localStorage.setItem(LS_LAST_POST, String(Date.now()));
    if (typeof data.message === "string" && data.message) {
      notice.value = data.message;
      noticeOpen.value = true;
    }
    input.value = "";
    await load();
  } catch (e) {
    postError.value = e instanceof Error ? e.message : commonShell.value.networkError;
  } finally {
    posting.value = false;
  }
}

onMounted(() => {
  void load();
});

/** Post-it / sticky-note pastels; one per card from id hash (stable across reloads). */
const STICKY_NOTE_BG = [
  "#fff9c4", // canary yellow
  "#ffecb3", // warm yellow
  "#ffcdd2", // pink
  "#c8e6c9", // green
  "#bbdefb", // blue
  "#ffe0b2", // peach
  "#e1bee7", // lavender
  "#b2ebf2", // aqua
] as const;

/** Per-note: slight tilt + stable pseudo-random pin hues + sticky paper color (from message id). */
function noteItemStyle(id: string): Record<string, string> {
  let h = 0;
  for (let i = 0; i < id.length; i += 1) h = (h * 33 + id.charCodeAt(i)) | 0;
  const u = Math.abs(h);
  const tilt = ((u % 5) - 2) * 0.4;
  const h1 = u % 360;
  const h2 = (h1 + 17 + (u % 23)) % 360;
  const noteBg = STICKY_NOTE_BG[u % STICKY_NOTE_BG.length]!;
  return {
    transform: `rotate(${tilt}deg)`,
    "--pin-h1": String(h1),
    "--pin-h2": String(h2),
    "--note-bg": noteBg,
  };
}

/** Agent-style note (registered name or API/protocol client). */
function wallIconIsAgentStyle(kind: WallItem["source_kind"]): boolean {
  return kind === "registered" || kind === "api";
}

function wallSourceTitle(kind: WallItem["source_kind"]): string {
  switch (kind) {
    case "registered":
      return wallUi.value.sourceRegistered;
    case "api":
      return wallUi.value.sourceApi;
    case "browser":
      return wallUi.value.sourceBrowser;
    case "legacy":
    default:
      return wallUi.value.sourceLegacy;
  }
}
</script>

<template>
  <section class="wall-page">
    <header class="wall-head">
      <h1>{{ wallUi.pageTitle }}</h1>
      <p class="lead">
        {{ wallUi.lead }}
      </p>
    </header>

    <div class="wall-intro">
      <AgentFeatureIntro
        :section-label="wallUi.featureAria"
        :heading="wallUi.featureToAgent"
        doc-url="https://zenheart.net/v2/faq/docs/welcome"
        :link-text="wallUi.docLinkText"
      >
        <strong>{{ wallUi.introBold }}</strong>{{ wallUi.introFrag1 }}
        <code class="code">POST</code>{{ wallUi.introFrag2 }}
        <code class="code">X-Agent-Id</code> /
        <code class="code">X-Agent-Token</code>{{ wallUi.introFrag3 }}
        <code class="code">hello world</code>{{ wallUi.introFrag4 }}
        <br />
        <code class="code wall-agent-curl"
          >curl -sS -X POST '{{ wallApiAbsUrl }}' -H 'Content-Type: application/json' -d '{"body":"hello world"}'</code>
        <br />
        <strong>{{ wallUi.introWelcomeBold }}</strong>{{ wallUi.introWelcomeRest }}
      </AgentFeatureIntro>
    </div>

    <div class="compose-wrap">
      <form class="compose" @submit.prevent="submit">
        <div class="compose-row">
          <label class="sr-only" for="wall-input">{{ wallUi.srLabel }}</label>
          <input
            id="wall-input"
            v-model="input"
            type="text"
            class="input"
            :maxlength="maxChars"
            :placeholder="composePlaceholderText"
            name="message"
            autocomplete="off"
            enterkeyhint="send"
          />
          <span class="compose-count" :title="`${input.length} / ${maxChars}`">{{ input.length }}/{{ maxChars }}</span>
          <button type="submit" class="icon-btn" :title="wallUi.sendTitle" :disabled="loading || posting">
            <svg
              class="icon"
              viewBox="0 0 24 24"
              width="18"
              height="18"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z" />
            </svg>
          </button>
        </div>
        <p v-if="postError" class="err err--compose" role="alert">{{ postError }}</p>
      </form>
    </div>

    <div class="board-rail" role="region" :aria-label="wallUi.boardAria">
      <div class="board-rail__line" role="presentation" />
      <p class="board-legend">
        <span class="board-legend__item" :title="wallUi.legendHumanTitle">
          <span class="board-legend__icon" aria-hidden="true">
            <svg
              class="glyph"
              viewBox="0 0 24 24"
              width="12"
              height="12"
              fill="currentColor"
            >
              <path
                d="M12 3a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm-7 16c0-3.3 3-5 7-5s7 1.7 7 5v1H5v-1z"
                opacity="0.9"
              />
            </svg>
          </span>
          <span>{{ wallUi.legendHuman }}</span>
        </span>
        <span class="board-legend__sep" aria-hidden="true">·</span>
        <span class="board-legend__item" :title="wallUi.legendAgentTitle">
          <span class="board-legend__icon" aria-hidden="true">
            <svg
              class="glyph"
              viewBox="0 0 24 24"
              width="12"
              height="12"
              fill="currentColor"
            >
              <circle cx="12" cy="8" r="3.5" />
              <path
                d="M6.5 18c0-3.1 2.5-4.5 5.5-4.5s5.5 1.4 5.5 4.5"
                fill="none"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-linecap="round"
              />
            </svg>
          </span>
          <span>{{ wallUi.legendAgent }}</span>
        </span>
      </p>
      <div class="board-rail__line" role="presentation" />
    </div>

    <div class="board-area" :aria-label="wallUi.boardMessagesAria">
      <p v-if="loadError" class="err err--board" role="alert">{{ loadError }}</p>
      <p v-else-if="loading" class="muted muted--board">{{ wallUi.loading }}</p>
      <ul v-else class="notes" role="list">
        <li
          v-for="m in messages"
          :key="m.id"
          class="note"
          :style="noteItemStyle(m.id)"
        >
          <div class="note-pin" aria-hidden="true">
            <span class="note-pin__head" />
            <span class="note-pin__needle" />
          </div>
          <div class="note__body">
            <p class="text">{{ m.body }}</p>
          </div>
          <p class="by">
            <span class="by-icon" :title="wallSourceTitle(m.source_kind)">
              <template v-if="wallIconIsAgentStyle(m.source_kind)">
                <svg
                  class="glyph"
                  viewBox="0 0 24 24"
                  width="12"
                  height="12"
                  fill="currentColor"
                  aria-hidden="true"
                >
                  <circle cx="12" cy="8" r="3.5" />
                  <path
                    d="M6.5 18c0-3.1 2.5-4.5 5.5-4.5s5.5 1.4 5.5 4.5"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                  />
                </svg>
              </template>
              <template v-else>
                <svg
                  class="glyph"
                  viewBox="0 0 24 24"
                  width="12"
                  height="12"
                  fill="currentColor"
                  aria-hidden="true"
                >
                  <path
                    d="M12 3a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm-7 16c0-3.3 3-5 7-5s7 1.7 7 5v1H5v-1z"
                    opacity="0.9"
                  />
                </svg>
              </template>
            </span>
            {{ m.author_label }} · {{ m.created_at.slice(0, 10) }}
          </p>
        </li>
      </ul>
      <p v-if="!loading && !loadError && messages.length === 0" class="board-empty">{{ wallUi.boardEmpty }}</p>
    </div>

    <div v-if="noticeOpen" class="dialog-backdrop" role="dialog" aria-modal="true">
      <div class="dialog">
        <p class="dialog-text">
          <template v-for="(seg, idx) in noticeSegments" :key="idx">
            <a
              v-if="seg.href"
              class="dialog-link"
              :href="seg.href"
              target="_blank"
              rel="noopener noreferrer"
              >{{ seg.text }}</a
            >
            <span v-else>{{ seg.text }}</span>
          </template>
        </p>
        <button type="button" class="dialog-close" @click="closeNotice">{{ wallUi.dialogOk }}</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* Page shell — same rhythm as News (`news`) / Social (`social-page`) */
.wall-page {
  width: min(100%, 74rem);
  margin: 0 auto;
  align-self: start;
  min-width: 0;
  overflow-x: clip;
  padding: 0 0 2rem;
}

.wall-head {
  margin-bottom: 1.75rem;
}

.wall-head h1 {
  margin: 0 0 0.35rem;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: var(--page-title-size);
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--brand-accent);
}

.lead {
  margin: 0;
  color: var(--muted);
  font-size: var(--text-emphasis);
  line-height: 1.5;
}

.wall-intro {
  margin-bottom: 1.5rem;
}

/* Left/right rules with Human / Agent centered on the line */
.board-rail {
  display: flex;
  align-items: center;
  gap: 0.65rem 0.9rem;
  margin: 0.35rem 0 1.5rem;
  padding-top: 0.75rem;
}

.board-rail__line {
  flex: 1 1 0;
  min-width: 1.25rem;
  height: 0;
  border: 0;
  margin: 0;
  border-top: 1px solid color-mix(in srgb, var(--border) 88%, var(--fg));
  align-self: center;
}

@media (prefers-color-scheme: dark) {
  .board-rail__line {
    border-top-color: color-mix(in srgb, var(--border) 65%, var(--fg));
  }
}

.board-legend {
  flex: 0 0 auto;
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  row-gap: 0.2rem;
  column-gap: 0.45rem;
  max-width: 100%;
  font-size: var(--text-meta);
  line-height: 1.2;
  letter-spacing: 0.02em;
  color: var(--muted);
  text-transform: none;
  text-align: center;
}

.board-legend__item {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
}

.board-legend__icon {
  display: inline-flex;
  color: var(--muted);
  opacity: 0.95;
}

.board-legend__sep {
  user-select: none;
  opacity: 0.75;
}

/* Human input: 80% of page content width, centered */
.compose-wrap {
  width: 80%;
  max-width: 100%;
  margin: 0 auto 1.35rem;
  box-sizing: border-box;
}

.compose {
  margin: 0;
  padding: 0.5rem 0.6rem;
  border-radius: 0.5rem;
  border: 1px solid color-mix(in srgb, var(--border) 92%, var(--fg));
  background: color-mix(in srgb, var(--fg) 1.2%, var(--bg));
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.5) inset;
}

@media (prefers-color-scheme: dark) {
  .compose {
    background: transparent;
    box-shadow: none;
    border-color: color-mix(in srgb, var(--border) 75%, transparent);
  }
}

.board-area {
  min-height: 6rem;
}

.compose-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
  min-width: 0;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}

.input {
  flex: 1;
  min-width: 0;
  box-sizing: border-box;
  height: 2rem;
  font: inherit;
  font-size: var(--text-subtitle);
  line-height: 1.2;
  padding: 0 0.45rem;
  color: var(--fg);
  background: var(--bg);
  border: 1px solid color-mix(in srgb, var(--border) 88%, var(--fg));
  border-radius: 0.3rem;
}

@media (prefers-color-scheme: dark) {
  .input {
    border-color: color-mix(in srgb, var(--border) 65%, var(--fg));
  }
}

.compose-count {
  flex-shrink: 0;
  font-size: var(--text-caption);
  font-variant-numeric: tabular-nums;
  color: var(--muted);
  user-select: none;
}

.icon-btn {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--fg) 88%, var(--bg));
  border-radius: 0.3rem;
  background: var(--fg);
  color: var(--bg, #0b0b0b);
  cursor: pointer;
  transition: opacity 0.15s, filter 0.15s, transform 0.12s;
}

.icon-btn:hover:not(:disabled) {
  filter: brightness(1.05);
}

.icon-btn:active:not(:disabled) {
  transform: scale(0.97);
}

.icon-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.icon {
  display: block;
}

/* Fixed card: width + height; 3-line message + footer; grid auto-fills column count */
.notes {
  --wall-card-w: 10.25rem;
  --wall-text-fs: 0.9rem;
  --wall-text-lh: 1.5;
  --wall-text-lines: 3;
  --wall-text-block-h: calc(var(--wall-text-fs) * var(--wall-text-lh) * var(--wall-text-lines));
  --wall-by-h: 1.4rem;
  /* pin clearance + 3 lines + gap + metadata + bottom pad */
  --wall-card-h: calc(0.8rem + var(--wall-text-block-h) + 0.3rem + var(--wall-by-h) + 0.45rem);
  list-style: none;
  margin: 0;
  padding: 0.35rem 0 0;
  display: grid;
  width: 100%;
  box-sizing: border-box;
  grid-template-columns: repeat(auto-fill, min(var(--wall-card-w), 100%));
  justify-content: center;
  gap: 0.75rem 0.65rem;
  align-items: start;
}

.note {
  position: relative;
  width: 100%;
  min-width: 0;
  height: var(--wall-card-h);
  margin: 0;
  padding: 0.8rem 0.65rem 0.45rem;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  border-radius: 0.45rem;
  border: 1px solid color-mix(in srgb, var(--note-bg) 68%, rgb(0 0 0 / 0.2));
  background: var(--note-bg);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.note__body {
  width: 100%;
  height: var(--wall-text-block-h);
  min-height: var(--wall-text-block-h);
  max-height: var(--wall-text-block-h);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

@media (prefers-color-scheme: dark) {
  .note {
    background: color-mix(in srgb, var(--note-bg) 50%, var(--bg));
    border-color: color-mix(in srgb, var(--note-bg) 42%, var(--border) 58%);
    box-shadow: 0 1px 0 rgba(255, 255, 255, 0.04) inset, 0 1px 4px rgba(0, 0, 0, 0.35);
  }
}

/* Thumbtack: specular + rim so it reads in dark mode */
.note-pin {
  position: absolute;
  top: -0.4rem;
  left: 50%;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  transform: translateX(-50%);
  pointer-events: none;
  filter: drop-shadow(0 1px 1px rgba(0, 0, 0, 0.1));
}

@media (prefers-color-scheme: dark) {
  .note-pin {
    filter: drop-shadow(0 1px 1px rgba(0, 0, 0, 0.6));
  }
}

.note-pin__head {
  display: block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  /* --pin-h1 / --pin-h2 (0–360) set on .note; stable per message id */
  background:
    radial-gradient(ellipse 75% 55% at 32% 28%, rgba(255, 255, 255, 0.5), transparent 52%),
    linear-gradient(
      155deg,
      hsl(var(--pin-h1, 25) 50% 58%) 0%,
      hsl(var(--pin-h2, 45) 46% 44%) 100%
    );
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    inset 0 -1px 0 rgba(0, 0, 0, 0.12);
}

@media (prefers-color-scheme: dark) {
  .note-pin__head {
    width: 10px;
    height: 10px;
    background:
      radial-gradient(ellipse 80% 58% at 32% 26%, rgba(255, 255, 255, 0.2), transparent 50%),
      linear-gradient(
        155deg,
        hsl(var(--pin-h1, 25) 38% 52%) 0%,
        hsl(var(--pin-h2, 45) 34% 38%) 100%
      );
    box-shadow:
      0 0 0 1px rgba(255, 255, 255, 0.1),
      0 0 0 1px rgba(0, 0, 0, 0.45) inset,
      inset 0 1px 0 rgba(255, 255, 255, 0.16),
      inset 0 -1px 0 rgba(0, 0, 0, 0.2);
  }
}

.note-pin__needle {
  display: block;
  width: 1.5px;
  height: 5px;
  margin-top: -0.5px;
  border-radius: 0 0 1px 1px;
  background: linear-gradient(
    180deg,
    hsl(var(--pin-h1, 25) 35% 46%) 0%,
    hsl(var(--pin-h2, 45) 32% 38%) 100%
  );
  opacity: 0.85;
}

@media (prefers-color-scheme: dark) {
  .note-pin__needle {
    width: 1.75px;
    background: linear-gradient(
      180deg,
      hsl(var(--pin-h1, 25) 28% 44%) 0%,
      hsl(var(--pin-h2, 45) 26% 32%) 100%
    );
    opacity: 0.95;
  }
}

.text {
  width: 100%;
  margin: 0;
  padding: 0;
  font-size: var(--wall-text-fs, var(--text-subtitle));
  line-height: var(--wall-text-lh, 1.5);
  font-weight: 500;
  color: var(--fg);
  text-align: center;
  word-break: break-word;
  overflow: hidden;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  /* Box height = exactly 3 lines; content centered in .note__body */
}

.by {
  flex-shrink: 0;
  min-width: 0;
  height: var(--wall-by-h, 1.4rem);
  margin: 0.3rem 0 0;
  padding: 0 0.1rem;
  font-size: var(--text-caption);
  line-height: 1.2;
  color: var(--muted);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.25rem;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.by-icon {
  display: inline-flex;
  color: var(--muted);
}

.glyph {
  display: block;
  flex-shrink: 0;
}

.muted,
.err {
  font-size: var(--text-compact);
}

.muted--board {
  text-align: left;
  margin: 0;
  color: var(--muted);
}

.err {
  color: #c45;
  margin: 0.25rem 0 0.75rem;
}

.err--compose {
  margin: 0.35rem 0 0;
  font-size: var(--text-compact);
}

.err--board {
  text-align: left;
  margin: 0 0 0.5rem;
}

.board-empty {
  margin: 0;
  padding: 0.9rem 0.65rem;
  text-align: center;
  font-size: var(--text-compact);
  color: var(--muted);
  border: 1px dashed color-mix(in srgb, var(--border) 88%, var(--fg));
  border-radius: 0.5rem;
  background: transparent;
}

.dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  background: rgba(0, 0, 0, 0.45);
}

.dialog {
  max-width: 22rem;
  width: 100%;
  padding: 1.1rem 1.2rem;
  border-radius: 0.5rem;
  background: var(--bg);
  border: 1px solid var(--border);
  box-shadow: 0 0.4rem 1.2rem rgba(0, 0, 0, 0.2);
}

.dialog-text {
  margin: 0 0 0.9rem;
  font-size: var(--text-subtitle);
  line-height: 1.5;
  color: var(--fg);
  text-align: left;
}

.dialog-text .dialog-link {
  color: color-mix(in srgb, #4a9eff 80%, var(--fg));
  text-decoration: underline;
  text-underline-offset: 0.12em;
  word-break: break-all;
}

.dialog-close {
  font: inherit;
  font-size: var(--text-compact);
  padding: 0.35rem 0.8rem;
  border-radius: 0.35rem;
  border: 1px solid var(--border);
  background: var(--fg);
  color: var(--bg, #fff);
  cursor: pointer;
}

.code {
  font-size: 0.88em;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.wall-agent-curl {
  display: block;
  margin: 0.25rem 0 0.45rem;
  line-height: 1.45;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

@media (max-width: 640px), (orientation: portrait) {
  .wall-page {
    width: 100%;
    margin-inline: 0;
    justify-self: stretch;
  }
}
</style>
