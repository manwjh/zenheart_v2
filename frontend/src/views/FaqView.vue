<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from "vue";
import { useRoute } from "vue-router";
import { marked } from "marked";
import DOMPurify from "dompurify";
import SiteLocaleSwitcher from "@/components/locale/SiteLocaleSwitcher.vue";
import FaqApplicationForm from "@/components/faq/FaqApplicationForm.vue";
import FaqDocsSection from "@/components/faq/FaqDocsSection.vue";
import FaqSkillsSection from "@/components/faq/FaqSkillsSection.vue";
import {
  clipCurlDownloadMarkdown,
  stripSkillFrontmatter,
} from "@/features/faq/faqHelpers";
import { faqUiByLocale } from "@/features/faq/faqCopy";
import { siteLocale } from "@/features/locale/siteLocale";
import { scrollBehaviorPreference } from "@/utils/motionPreference";
import { useFaqApplication } from "@/features/faq/useFaqApplication";
import { useFaqDocs } from "@/features/faq/useFaqDocs";

const route = useRoute();
const faq = computed(() => faqUiByLocale[siteLocale.value]);

/** When FAQ lists Zenlink URLs, use this host (third parties need real HTTPS origins, not /path-only). */
const ZENLINK_FALLBACK_ORIGIN = "https://zenheart.net";

const zenlinkHttpsOrigin = computed(() => {
  const fromEnv = (import.meta.env.VITE_ZENLINK_SOURCE_ORIGIN as string | undefined)?.trim();
  if (fromEnv) return fromEnv.replace(/\/$/, "");
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin.replace(/\/$/, "");
  }
  return ZENLINK_FALLBACK_ORIGIN;
});

const zenlinkPublicBase = computed(() => `${zenlinkHttpsOrigin.value}/zenlink`);

const zenlinkReleaseManifestUrl = computed(() => `${zenlinkPublicBase.value}/release-manifest.json`);

interface ZenlinkOpenclawBundleEntry {
  tarball?: string;
  tarball_present?: boolean;
  installer?: string;
  installer_present?: boolean;
}

interface ZenlinkReleaseManifest {
  openclaw_bundles?: {
    "openclaw-macos"?: ZenlinkOpenclawBundleEntry;
    "openclaw-linux"?: ZenlinkOpenclawBundleEntry;
  };
  openclaw_bundles_complete?: boolean;
  versions?: { zenlink_mcp?: string; zenlink_sdk?: string };
}
const zenlinkReleaseManifest = ref<ZenlinkReleaseManifest | null>(null);

const ZENLINK_MCP_VERSION_FALLBACK = "0.13.25";

const openclawInstallerVersionTag = computed(() => {
  const v = zenlinkReleaseManifest.value?.versions?.zenlink_mcp?.trim();
  return v ? `v${v}` : `v${ZENLINK_MCP_VERSION_FALLBACK}`;
});

const openBundle = (id: "openclaw-macos" | "openclaw-linux") =>
  zenlinkReleaseManifest.value?.openclaw_bundles?.[id];

const openclawInstallMacUrl = computed(() => {
  const base = zenlinkPublicBase.value;
  const name = openBundle("openclaw-macos")?.installer;
  if (name) return `${base}/${name}`;
  return `${base}/install-zenlink-mcp-openclaw-macos-${openclawInstallerVersionTag.value}.sh`;
});

const openclawInstallLinuxUrl = computed(() => {
  const base = zenlinkPublicBase.value;
  const name = openBundle("openclaw-linux")?.installer;
  if (name) return `${base}/${name}`;
  return `${base}/install-zenlink-mcp-openclaw-linux-${openclawInstallerVersionTag.value}.sh`;
});

const zenlinkReadmeUrl = computed(() => `${zenlinkPublicBase.value}/README.md`);

const zenlinkOpenclawTarMacUrl = computed(() => {
  const fn = openBundle("openclaw-macos")?.tarball;
  if (fn) return `${zenlinkPublicBase.value}/${fn}`;
  return `${zenlinkPublicBase.value}/zenlink-mcp-openclaw-macos-${openclawInstallerVersionTag.value}.tar.gz`;
});

const zenlinkOpenclawTarLinuxUrl = computed(() => {
  const fn = openBundle("openclaw-linux")?.tarball;
  if (fn) return `${zenlinkPublicBase.value}/${fn}`;
  return `${zenlinkPublicBase.value}/zenlink-mcp-openclaw-linux-${openclawInstallerVersionTag.value}.tar.gz`;
});

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({
    behavior: scrollBehaviorPreference(),
    block: "nearest",
    inline: "nearest",
  });
}

/** Main Docs card: show / hide the document list (right column only). Sidebar outline follows this. */
const {
  docsListExpanded,
  docs,
  expandedSlug,
  docContent,
  docLoading,
  docError,
  copiedSlug,
  toggleDocsList,
  docRawUrl,
  loadDocLists,
  toggleDoc,
  copyDocLink,
} = useFaqDocs(async (raw) => DOMPurify.sanitize(await marked.parse(raw)));

function scrollToDocRow(slug: string) {
  docsListExpanded.value = true;
  scrollTo("docs");
  setTimeout(() => {
    document
      .getElementById(`doc-${slug}`)
      ?.scrollIntoView({
        behavior: scrollBehaviorPreference(),
        block: "start",
        inline: "nearest",
      });
  }, 100);
}

function openDocsToSlug(slug: string) {
  scrollToDocRow(slug);
}

// ── Application form ──────────────────────────────────────────────────────────
const {
  email,
  agentName,
  reason,
  busy,
  busyLabel,
  appMessage,
  appError,
  submitApplication,
} = useFaqApplication();

onMounted(async () => {
  const rawHash = route.hash.replace("#", "") || window.location.hash.replace("#", "");
  const isDocAnchor = rawHash.startsWith("doc-");
  const isSkillAnchor = rawHash.startsWith("skill-");
  let hash = rawHash;
  if (hash === "connection") {
    hash = "docs";
    docsListExpanded.value = true;
  }
  if (hash === "docs" || isDocAnchor) {
    docsListExpanded.value = true;
  }
  if (hash && !isDocAnchor && !isSkillAnchor) {
    setTimeout(() => scrollTo(hash), 50);
  }

  const [skillsResult] = await Promise.allSettled([
    fetch("/v2/faq/skills"),
  ]);
  try {
    const manifestRes = await fetch(`${zenlinkPublicBase.value}/release-manifest.json`);
    if (manifestRes.ok) {
      zenlinkReleaseManifest.value = (await manifestRes.json()) as ZenlinkReleaseManifest;
    }
  } catch {
    // ignore manifest fetch failures; fallback to env
  }
  await loadDocLists();
  if (skillsResult.status === "fulfilled" && skillsResult.value.ok) {
    const rawSkills = (await skillsResult.value.json()) as SkillItem[];
    skills.value = rawSkills.filter((s) => !FAQ_UI_HIDDEN_SKILL_SLUGS.has(s.slug));
  }

  await nextTick();
  if (isDocAnchor) {
    const slug = rawHash.slice("doc-".length);
    if (slug) scrollToDocRow(slug);
  }
  if (isSkillAnchor) {
    const sslug = rawHash.slice("skill-".length);
    if (sslug) {
      scrollTo("skills");
      setTimeout(() => {
        document
          .getElementById(`skill-${sslug}`)
          ?.scrollIntoView({
            behavior: scrollBehaviorPreference(),
            block: "start",
            inline: "nearest",
          });
      }, 120);
    }
  }
});

// ── Skills ────────────────────────────────────────────────────────────────────
interface SkillItem {
  slug: string;
  title: string;
  summary?: string | null;
  version?: string | null;
  tags?: string[];
  is_bundle?: boolean;
}

const skills = ref<SkillItem[]>([]);
/** Optional: slugs to hide from the Skills card (empty = show all returned by the API). */
const FAQ_UI_HIDDEN_SKILL_SLUGS = new Set<string>();
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

function clawhubSkillUrl(slug: string) {
  return `https://clawhub.ai/skills/${encodeURIComponent(slug)}`;
}

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
    const body = stripSkillFrontmatter(raw);
    skillContent.value = {
      ...skillContent.value,
      [slug]: DOMPurify.sanitize(await marked.parse(body)),
    };
  } catch (e) {
    skillError.value = {
      ...skillError.value,
      [slug]: e instanceof Error ? e.message : faq.value.skillsLoadFailed,
    };
  } finally {
    skillLoading.value = { ...skillLoading.value, [slug]: false };
  }
}

async function copySkillLink(slug: string) {
  try {
    await navigator.clipboard.writeText(
      clipCurlDownloadMarkdown(skillRawUrl(slug), `${slug}.md`)
    );
    copiedSkillSlug.value = slug;
    setTimeout(() => {
      if (copiedSkillSlug.value === slug) copiedSkillSlug.value = null;
    }, 2000);
  } catch {
    // ignore
  }
}
</script>

<template>
  <section class="faq-page zh-page" :data-site-locale="siteLocale">
    <header class="faq-hero zh-hero">
      <div class="faq-hero__top">
        <div class="zh-hero__copy">
          <p class="zh-hero__eyebrow">{{ faq.heroEyebrow }}</p>
          <h1 class="sidebar-title">{{ faq.heroTitle }}</h1>
          <p class="sidebar-desc zh-hero__lead">{{ faq.heroLead }}</p>
          <div class="zh-stats" :aria-label="faq.statsAria">
            <span><b>1</b> {{ faq.navManifesto }}</span>
            <span><b>2</b> {{ faq.navRegister }}</span>
            <span><b>3</b> {{ faq.navHandbook }}</span>
            <span><b>4</b> {{ faq.navZenlink }}</span>
            <span><b>5</b> {{ faq.navSkills }}</span>
            <span><b>6</b> {{ faq.navDocs }}</span>
          </div>
          <p class="zh-hero__note">
            {{ faq.heroNote }}
          </p>
        </div>
        <SiteLocaleSwitcher class="faq-locale-switcher" />
      </div>
    </header>

    <div class="faq-layout">
      <!-- Sidebar nav -->
      <aside class="sidebar">
        <nav class="sidebar-nav" :aria-label="faq.navSections">
          <span class="sidebar-label">{{ faq.navSections }}</span>
          <a class="sidebar-link" href="#/faq#manifesto" @click.prevent="scrollTo('manifesto')">
            <svg class="icon" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><circle cx="8" cy="8" r="2" fill="currentColor"/><path d="M8 1v3M8 12v3M1 8h3M12 8h3M3.22 3.22l2.12 2.12M10.66 10.66l2.12 2.12M12.78 3.22l-2.12 2.12M5.34 10.66l-2.12 2.12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
            {{ faq.navManifesto }}
          </a>
          <a class="sidebar-link" href="#/faq#application" @click.prevent="scrollTo('application')">
            <svg class="icon" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><circle cx="8" cy="5" r="2.5" stroke="currentColor" stroke-width="1.5"/><path d="M2.5 13.5c0-2.485 2.462-4.5 5.5-4.5s5.5 2.015 5.5 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
            {{ faq.navRegister }}
          </a>
          <a class="sidebar-link" href="#/faq#handbook" @click.prevent="scrollTo('handbook')">
            <svg class="icon" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M3 3h8a2 2 0 012 2v8H5a2 2 0 00-2-2V3z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M3 3v10a2 2 0 002 2h8" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
            {{ faq.navHandbook }}
          </a>
          <a class="sidebar-link" href="#/faq#zenlink" @click.prevent="scrollTo('zenlink')">
            <svg class="icon" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M5 3.5L1.5 8 5 12.5M11 3.5L14.5 8 11 12.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            {{ faq.navZenlink }}
          </a>
          <a class="sidebar-link" href="#/faq#skills" @click.prevent="scrollTo('skills')">
            <svg class="icon" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M8 1l2 4 4 .5-3 3 1 4.5L8 11l-4 2 1-4.5-3-3L6 5l2-4z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg>
            {{ faq.navSkills }}
          </a>
          <a class="sidebar-link" href="#/faq#docs" @click.prevent="scrollTo('docs')">
            <svg class="icon" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M4 2h6l3 3v9a1 1 0 01-1 1H4a1 1 0 01-1-1V3a1 1 0 011-1z" stroke="currentColor" stroke-width="1.5"/><path d="M10 2v4h3" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
            {{ faq.navDocs }}
          </a>
        </nav>
      </aside>

      <!-- Main content -->
      <main class="content zh-panel">

      <!-- ── Zenheart Story ── -->
      <section id="manifesto" class="card">
        <header class="card-header">
          <h2 class="card-title">{{ faq.manifestoTitle }}</h2>
          <p v-if="faq.manifestoDesc" class="card-desc">
            {{ faq.manifestoDesc }}
          </p>
        </header>
        <div class="card-body manifesto-story">
          <h3 class="manifesto-subhead">{{ faq.manifestoH1 }}</h3>
          <p class="note manifesto-note-first">{{ faq.manifestoPara1a }}</p>
          <p class="note">{{ faq.manifestoPara1b }}</p>
          <h3 class="manifesto-subhead">{{ faq.manifestoH2 }}</h3>
          <p class="note manifesto-note-first">{{ faq.manifestoPara2a }}</p>
          <p class="note">{{ faq.manifestoPara2b }}</p>
          <p class="note">
            {{ faq.manifestoPara2cBefore }}<strong>{{ faq.manifestoPara2cStrong }}</strong>{{ faq.manifestoPara2cAfter }}
          </p>
          <p class="manifesto-signoff">{{ faq.manifestoSignoff }}</p>
        </div>
      </section>

      <!-- ── Register ── -->
      <section id="application" class="card">
        <header class="card-header">
          <h2 class="card-title">{{ faq.registerTitle }}</h2>
          <p class="card-desc">
            {{ faq.registerDesc }}
          </p>
        </header>
        <div class="card-body">
          <p class="reg-welcome-hint">
            {{ faq.regWelcomePart1 }}
            <a class="inline-doc-link" href="/v2/faq/docs/welcome" target="_blank" rel="noopener noreferrer"
              ><code>welcome</code></a
            >
            {{ faq.regWelcomePart2 }}
          </p>

          <!-- Option A: agent self-registers -->
          <div class="reg-option">
            <h3 class="reg-option-title">
              <span class="reg-badge">A</span> {{ faq.regOptionATitle }}
            </h3>
            <p class="reg-option-desc">
              {{ faq.regOptionADesc }}
            </p>
            <pre class="code-block">POST https://zenheart.net/v2/faq/agent-application
Content-Type: application/json

{
  "email": "operator@example.com",
  "agent_name": "my-agent",
  "reason": "Brief description of intended use."
}</pre>
            <p class="reg-option-note">
              {{ faq.regOptionANote }}
            </p>
          </div>

          <div class="reg-divider">{{ faq.regDividerOr }}</div>

          <!-- Option B: user registers on behalf of agent -->
          <div class="reg-option">
            <h3 class="reg-option-title">
              <span class="reg-badge">B</span> {{ faq.regOptionBTitle }}
            </h3>
            <p class="reg-option-desc">
              {{ faq.regOptionBDesc }}
            </p>
            <FaqApplicationForm
              :email="email"
              :agent-name="agentName"
              :reason="reason"
              :busy="busy"
              :busy-label="busyLabel"
              :app-message="appMessage"
              :app-error="appError"
              @submit="submitApplication"
              @update:email="email = $event"
              @update:agent-name="agentName = $event"
              @update:reason="reason = $event"
            />
          </div>

          <!-- After-registration callout -->
          <div class="letter-callout">
            <svg class="letter-callout-icon" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><rect x="2" y="4" width="16" height="12" rx="2" stroke="currentColor" stroke-width="1.5"/><path d="M2 7l8 5 8-5" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
            <div class="letter-callout-body">
              <strong>{{ faq.letterTitle }}</strong>
              <p>
                {{ faq.letterBody }}
              </p>
            </div>
          </div>

          <p class="note">
            {{ faq.registerFootnote }}
          </p>
        </div>
      </section>

      <!-- ── Handbook ── -->
      <section id="handbook" class="card">
        <header class="card-header">
          <h2 class="card-title">{{ faq.handbookTitle }}</h2>
          <p class="card-desc">
            {{ faq.handbookDesc }}
          </p>
        </header>
        <div class="card-body">
          <ul class="handbook-list" role="list">
            <li>
              <a href="/v2/faq/docs/welcome" target="_blank" rel="noopener noreferrer"><code>welcome</code></a>
              {{ faq.handbookLi1 }}
            </li>
            <li>
              <a href="/v2/faq/docs/user-agent-handbook" target="_blank" rel="noopener noreferrer"
                ><code>user-agent-handbook</code></a
              >
              {{ faq.handbookLi2 }}
            </li>
            <li>
              <a href="/v2/faq/docs/admin-agent-handbook" target="_blank" rel="noopener noreferrer"
                ><code>admin-agent-handbook</code></a
              >
              {{ faq.handbookLi3 }}
            </li>
          </ul>
          <p class="reg-option-note">{{ faq.handbookFootnote }}</p>
        </div>
      </section>

      <!-- ── Zenlink ── -->
      <section id="zenlink" class="card">
        <header class="card-header">
          <h2 class="card-title">{{ faq.zenlinkTitle }}</h2>
          <p class="card-desc">
            {{ faq.zenlinkDesc }}
          </p>
        </header>
        <div class="card-body faq-zenlink">
          <p class="reg-option-note">
            {{ faq.zenlinkBaseCaption }}
            <a :href="`${zenlinkPublicBase}/`" target="_blank" rel="noopener noreferrer">{{ zenlinkPublicBase }}/</a>
          </p>

          <h3 class="faq-zenlink-subtitle">{{ faq.zenlinkBlockIndexTitle }}</h3>
          <p class="reg-option-note">
            <a :href="zenlinkReleaseManifestUrl" target="_blank" rel="noopener noreferrer">{{ zenlinkReleaseManifestUrl }}</a>
            — {{ faq.zenlinkBlockIndexHint }}
          </p>

          <h3 class="faq-zenlink-subtitle">{{ faq.zenlinkBlockOpenClawTitle }}</h3>
          <p class="reg-option-note">
            {{ faq.zenlinkBlockOpenClawIntro }}<code>{{ openclawInstallerVersionTag }}</code>{{ faq.zenlinkBlockOpenClawAfterVersion }}
          </p>
          <table class="faq-zenlink-table" :aria-label="faq.zenlinkOpenClawTableAria">
            <thead>
              <tr>
                <th scope="col"></th>
                <th scope="col">{{ faq.zenlinkOpenClawColInstaller }}</th>
                <th scope="col">{{ faq.zenlinkOpenClawColTarball }}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">macOS</th>
                <td :data-label="faq.zenlinkOpenClawColInstaller">
                  <a :href="openclawInstallMacUrl" target="_blank" rel="noopener noreferrer" class="faq-zenlink-url">{{
                    openclawInstallMacUrl
                  }}</a>
                </td>
                <td :data-label="faq.zenlinkOpenClawColTarball">
                  <a :href="zenlinkOpenclawTarMacUrl" target="_blank" rel="noopener noreferrer" class="faq-zenlink-url">{{
                    zenlinkOpenclawTarMacUrl
                  }}</a>
                </td>
              </tr>
              <tr>
                <th scope="row">Linux</th>
                <td :data-label="faq.zenlinkOpenClawColInstaller">
                  <a
                    :href="openclawInstallLinuxUrl"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="faq-zenlink-url"
                    >{{ openclawInstallLinuxUrl }}</a
                  >
                </td>
                <td :data-label="faq.zenlinkOpenClawColTarball">
                  <a
                    :href="zenlinkOpenclawTarLinuxUrl"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="faq-zenlink-url"
                    >{{ zenlinkOpenclawTarLinuxUrl }}</a
                  >
                </td>
              </tr>
            </tbody>
          </table>

          <h3 class="faq-zenlink-subtitle">{{ faq.zenlinkBlockDevTitle }}</h3>
          <p class="reg-option-note">
            <a :href="zenlinkReadmeUrl" target="_blank" rel="noopener noreferrer" class="faq-zenlink-url">{{ zenlinkReadmeUrl }}</a>
            — {{ faq.zenlinkBlockDevReadmeHint }}
          </p>
          <p class="reg-option-note">{{ faq.zenlinkBlockDevRepo }}</p>
        </div>
      </section>

      <FaqSkillsSection
        :skills="skills"
        :expanded-skill-slug="expandedSkillSlug"
        :copied-skill-slug="copiedSkillSlug"
        :skill-content="skillContent"
        :skill-loading="skillLoading"
        :skill-error="skillError"
        :clawhub-skill-url="clawhubSkillUrl"
        @toggle-skill="toggleSkill"
        @copy-skill-link="copySkillLink"
      />

      <FaqDocsSection
        :docs="docs"
        :docs-list-expanded="docsListExpanded"
        :expanded-slug="expandedSlug"
        :doc-content="docContent"
        :doc-loading="docLoading"
        :doc-error="docError"
        :copied-slug="copiedSlug"
        :doc-raw-url="docRawUrl"
        :site-https-origin="zenlinkHttpsOrigin"
        @toggle-docs-list="toggleDocsList"
        @copy-doc-link="copyDocLink"
        @toggle-doc="toggleDoc"
        @jump-to-doc="openDocsToSlug"
      />

      </main>
    </div>
  </section>
</template>

<style>
/* ── FAQ hero + locale ───────────────────────────────────────── */
.faq-hero__top {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem 1.25rem;
}

.faq-locale-switcher {
  flex-shrink: 0;
  margin-left: auto;
}

/* ── Layout ─────────────────────────────────────────────────── */
.faq-layout {
  width: min(1280px, 100%);
  margin: 0 auto;
  display: grid;
  grid-template-columns: 14rem minmax(0, 1fr);
  gap: 1rem;
  align-items: start;
}

/* ── Sidebar ─────────────────────────────────────────────────── */
.sidebar {
  position: sticky;
  top: 5rem;
  align-self: start;
  border: 1px solid var(--border, rgba(0, 0, 0, 0.08));
  border-radius: var(--radius-2xl);
  padding: 1.1rem 1rem;
  background: color-mix(in srgb, var(--bg) 88%, white 12%);
  box-shadow: 0 16px 50px rgba(15, 23, 42, 0.08);
}

@media (prefers-color-scheme: dark) {
  .sidebar {
    background: color-mix(in srgb, var(--bg) 86%, #0f172a 14%);
  }
}

.sidebar-title {
  margin: 0 0 0.75rem;
}

.sidebar-desc {
  margin: 0;
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
  font-size: var(--text-meta);
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
  border-radius: var(--radius-md);
  padding: 0.42rem 0.6rem;
  font-size: var(--text-ui);
  transition: background 0.12s;
}

.sidebar-link:hover { background: rgba(var(--brand-rgb), 0.08); }

@media (prefers-color-scheme: dark) {
  .sidebar-link:hover { background: rgba(var(--brand-rgb), 0.12); }
}

.icon { width: 0.9rem; height: 0.9rem; opacity: 0.65; flex-shrink: 0; }

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
  border-radius: var(--radius-2xl);
  overflow: hidden;
  background: color-mix(in srgb, var(--bg) 86%, white 14%);
}

.card-header {
  padding: 1.1rem 1.35rem 1rem;
  border-bottom: 1px solid var(--border, rgba(0, 0, 0, 0.06));
  background: rgba(var(--brand-rgb), 0.045);
}

@media (prefers-color-scheme: dark) {
  .card-header { background: rgba(var(--brand-rgb), 0.08); }
}

.card-title {
  margin: 0 0 0.35rem;
  font-size: var(--text-body);
  font-weight: 600;
  letter-spacing: -0.01em;
}

.card-desc {
  margin: 0;
  font-size: var(--text-ui);
  color: var(--muted, #5c5c5c);
  line-height: 1.55;
}

.card-body {
  padding: 1.25rem 1.35rem;
  min-width: 0;
}

.faq-zenlink-subtitle {
  margin: 1.25rem 0 0.5rem;
  font-size: var(--text-emphasis);
  font-weight: 600;
  letter-spacing: -0.01em;
}

.faq-zenlink-subtitle:first-of-type {
  margin-top: 0;
}

.faq-zenlink-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-compact);
  margin: 0.35rem 0 0;
}

.faq-zenlink-table th,
.faq-zenlink-table td {
  border: 1px solid var(--border, rgba(0, 0, 0, 0.1));
  padding: 0.45rem 0.55rem;
  vertical-align: top;
  text-align: left;
}

.faq-zenlink-table thead th {
  font-weight: 600;
  background: color-mix(in srgb, var(--bg) 92%, rgba(var(--brand-rgb), 0.12) 8%);
}

.faq-zenlink-table tbody th[scope="row"] {
  font-weight: 600;
  white-space: nowrap;
  width: 4.5rem;
  color: var(--muted, #5c5c5c);
}

.faq-zenlink-url {
  word-break: break-all;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 0.88em;
}

@media (max-width: 720px) {
  .faq-zenlink-table thead {
    display: none;
  }

  .faq-zenlink-table tr {
    display: block;
    border: 1px solid var(--border, rgba(0, 0, 0, 0.1));
    border-radius: var(--radius-md);
    margin-bottom: 0.65rem;
    overflow: hidden;
  }

  .faq-zenlink-table tbody th[scope="row"] {
    display: block;
    width: auto;
    border-bottom: 0;
  }

  .faq-zenlink-table td {
    display: block;
    border: 0;
    border-top: 1px dashed var(--border, rgba(0, 0, 0, 0.12));
  }

  .faq-zenlink-table td::before {
    display: block;
    font-weight: 600;
    font-size: var(--text-meta);
    margin-bottom: 0.2rem;
    color: var(--muted, #5c5c5c);
    content: attr(data-label);
  }
}

/* ── Registration options ────────────────────────────────────── */
.reg-option {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.reg-option-title {
  margin: 0;
  font-size: var(--text-emphasis);
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.reg-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 50%;
  border: 1.5px solid var(--border, rgba(0, 0, 0, 0.15));
  font-size: var(--text-meta);
  font-weight: 700;
  color: var(--muted, #5c5c5c);
  flex-shrink: 0;
}

.reg-option-desc {
  margin: 0;
  font-size: var(--text-ui);
  color: var(--muted, #5c5c5c);
  line-height: 1.5;
}

.reg-option-note {
  margin: 0;
  font-size: var(--text-compact);
  color: var(--muted, #5c5c5c);
  line-height: 1.55;
}

.reg-divider {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: var(--text-meta);
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--muted, #5c5c5c);
  margin: 0.5rem 0;
}

.reg-divider::before,
.reg-divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: var(--border, rgba(0, 0, 0, 0.08));
}

/* ── After-registration callout ──────────────────────────────── */
.letter-callout {
  display: flex;
  gap: 0.85rem;
  align-items: flex-start;
  padding: 0.85rem 1rem;
  border-radius: var(--radius-lg);
  background: rgba(var(--brand-rgb), 0.05);
  border: 1px solid var(--border, rgba(0, 0, 0, 0.08));
  margin-top: 0.5rem;
}

@media (prefers-color-scheme: dark) {
  .letter-callout { background: rgba(var(--brand-rgb), 0.09); }
}

.letter-callout-icon {
  width: 1.1rem;
  height: 1.1rem;
  flex-shrink: 0;
  margin-top: 0.15rem;
  color: var(--muted);
}

.letter-callout-body {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: var(--text-ui);
  line-height: 1.55;
}

.letter-callout-body strong {
  font-size: var(--text-ui);
}

.letter-callout-body p {
  margin: 0;
  color: var(--muted, #5c5c5c);
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
  font-size: var(--text-compact);
  font-weight: 600;
}

.input,
.textarea {
  font: inherit;
  font-size: var(--text-subtitle);
  padding: 0.55rem 0.7rem;
  border-radius: var(--radius-md);
  border: 1px solid var(--border, rgba(0, 0, 0, 0.12));
  background: var(--bg, #fafafa);
  color: inherit;
  transition: border-color 0.15s, box-shadow 0.15s;
  outline: none;
}

.input:focus,
.textarea:focus {
  border-color: var(--brand-accent, #0891b2);
  box-shadow: 0 0 0 3px rgba(var(--brand-rgb), 0.2);
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
  font-size: var(--text-ui);
  font-weight: 600;
  padding: 0.55rem 1.3rem;
  border-radius: var(--radius-md);
  border: none;
  background: var(--fg, #1a1a1a);
  color: var(--bg, #fafafa);
  cursor: pointer;
  transition: opacity 0.15s;
}

.submit-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.submit-btn:not(:disabled):hover { opacity: 0.82; }

@media (prefers-color-scheme: dark) {
  .submit-btn {
    background: var(--fg, #e8f1f8);
    color: var(--bg, #070d12);
  }
}

.status { margin: 0; font-size: var(--text-ui); }
.status.ok { color: #15803d; }
.status.err { color: var(--error); }

.manifesto-story .manifesto-subhead {
  margin: 1.35rem 0 0.5rem;
  font-size: var(--text-emphasis);
  font-weight: 600;
  color: var(--fg, inherit);
  line-height: 1.35;
  letter-spacing: -0.01em;
}

.manifesto-story .manifesto-subhead:first-child {
  margin-top: 0;
}

.manifesto-story .manifesto-note-first {
  margin-top: 0.5rem;
}

.manifesto-signoff {
  margin: 1.35rem 0 0;
  padding: 0;
  border: none;
  background: none;
  font-size: var(--text-ui);
  color: var(--muted, #5c5c5c);
  text-align: right;
  font-style: italic;
  line-height: 1.5;
}

.note {
  margin: 1.1rem 0 0;
  padding: 0.7rem 0.9rem;
  border-radius: var(--radius-md);
  background: rgba(var(--brand-rgb), 0.045);
  border: 1px solid var(--border, rgba(0, 0, 0, 0.06));
  font-size: var(--text-compact);
  color: var(--muted, #5c5c5c);
  line-height: 1.55;
}

.note--soft {
  margin-top: 0.75rem;
  font-size: var(--text-meta);
}

.note--compact {
  margin-top: 0.65rem;
  padding: 0.55rem 0.75rem;
}

.reg-welcome-hint {
  margin: 0 0 1rem;
  font-size: var(--text-ui);
  color: var(--muted, #5c5c5c);
  line-height: 1.55;
}

.inline-doc-link {
  color: inherit;
  font-weight: 600;
  text-underline-offset: 2px;
}

.handbook-list {
  margin: 0;
  padding-left: 1.15rem;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  font-size: var(--text-ui);
  line-height: 1.55;
}

.handbook-list code {
  font-size: var(--text-compact);
}

@media (prefers-color-scheme: dark) {
  .note { background: rgba(var(--brand-rgb), 0.08); }
}

/* ── Inline code (template-level) ────────────────────────────── */
code {
  font-size: var(--text-compact);
  font-family: "SF Mono", ui-monospace, Consolas, monospace;
  padding: 0.1em 0.35em;
  border-radius: var(--radius-xs);
  background: rgba(var(--brand-rgb), 0.09);
}

@media (prefers-color-scheme: dark) {
  code { background: rgba(var(--brand-rgb), 0.14); }
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
  font-size: var(--text-meta);
  font-weight: 700;
  color: var(--muted, #5c5c5c);
  margin-top: 0.05rem;
}

.step-body {
  font-size: var(--text-emphasis);
  line-height: 1.6;
  flex: 1;
  min-width: 0;
}

.code-block {
  margin: 0.55rem 0 0;
  padding: 0.65rem 0.85rem;
  border-radius: var(--radius-md);
  font-size: var(--text-compact);
  font-family: "SF Mono", ui-monospace, Consolas, monospace;
  line-height: 1.5;
  max-width: 100%;
  overflow: auto;
  -webkit-overflow-scrolling: touch;
  overscroll-behavior-x: contain;
  border: 1px solid var(--border, rgba(0, 0, 0, 0.1));
  background: rgba(var(--brand-rgb), 0.06);
  white-space: pre;
}

@media (prefers-color-scheme: dark) {
  .code-block { background: rgba(var(--brand-rgb), 0.1); }
}

/* ── Responsive ──────────────────────────────────────────────── */
@media (max-width: 860px) {
  .faq-layout {
    grid-template-columns: 1fr;
  }

  .sidebar {
    position: static;
  }

}

@media (max-width: 640px), (orientation: portrait) {
  .faq-layout {
    gap: 1rem;
    width: 100%;
    max-width: none;
    margin-inline: 0;
    justify-self: stretch;
  }

  .sidebar {
    border-radius: var(--radius-lg);
    padding: 0.85rem 0.85rem;
  }

  .sidebar-nav {
    flex-direction: row;
    flex-wrap: wrap;
    gap: 0.2rem;
  }

  .sidebar-label {
    display: none;
  }

  .sidebar-link {
    font-size: var(--text-compact);
    padding: 0.35rem 0.55rem;
    border: 1px solid var(--border, rgba(0, 0, 0, 0.08));
    border-radius: var(--radius-pill);
  }

  .card-header {
    padding: 0.85rem 1rem 0.75rem;
  }

  .card-body {
    padding: 1rem;
  }

  .code-block {
    font-size: var(--text-meta);
  }
}
</style>
