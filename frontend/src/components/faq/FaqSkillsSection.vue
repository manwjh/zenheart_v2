<script setup lang="ts">
import { computed } from "vue";
import { faqUiByLocale } from "@/features/faq/faqCopy";
import { siteLocale } from "@/features/locale/siteLocale";

type SkillItem = {
  slug: string;
  title: string;
  summary?: string | null;
  version?: string | null;
  tags?: string[];
  is_bundle?: boolean;
};

defineProps<{
  skills: SkillItem[];
  expandedSkillSlug: string | null;
  copiedSkillSlug: string | null;
  skillContent: Record<string, string>;
  skillLoading: Record<string, boolean>;
  skillError: Record<string, string>;
  clawhubSkillUrl: (slug: string) => string;
}>();

const emit = defineEmits<{
  toggleSkill: [slug: string];
  copySkillLink: [slug: string];
}>();

const ui = computed(() => faqUiByLocale[siteLocale.value]);

const skillsDescParts = computed(() => {
  const s = ui.value.skillsDesc;
  const sep = "<slug>.md";
  const i = s.indexOf(sep);
  if (i < 0) return { before: s, after: "" };
  return { before: s.slice(0, i), after: s.slice(i + sep.length) };
});

function curlTitle(slug: string) {
  return ui.value.skillsCurlTitle.replace(/\{slug\}/g, slug);
}
</script>

<template>
  <section id="skills" class="card">
    <header class="card-header">
      <h2 class="card-title">{{ ui.skillsTitle }}</h2>
      <p class="card-desc">
        {{ skillsDescParts.before }}<code>&lt;slug&gt;.md</code>{{ skillsDescParts.after }}
      </p>
    </header>

    <div v-if="skills.length === 0" class="doc-empty">
      <svg class="doc-empty-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M3 9l9-5 9 5v11a1 1 0 01-1 1H4a1 1 0 01-1-1V9z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M9 22V12h6v10" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
      <span>{{ ui.skillsEmpty }}</span>
    </div>

    <ul v-else class="doc-list" role="list">
      <li
        v-for="skill in skills"
        :id="'skill-' + skill.slug"
        :key="skill.slug"
        class="doc-item skill-item"
      >
        <div class="skill-hub">
          <div class="skill-hub-main">
            <div class="skill-hub-title-row">
              <h3 class="skill-hub-name">{{ skill.title }}</h3>
              <span v-if="skill.version" class="skill-hub-version">v{{ skill.version }}</span>
            </div>
            <p v-if="skill.summary" class="skill-hub-summary">{{ skill.summary }}</p>
            <div v-if="skill.tags && skill.tags.length" class="skill-hub-tags">
              <span v-for="tag in skill.tags" :key="tag" class="skill-hub-tag">{{ tag }}</span>
            </div>
            <code class="skill-hub-slug">{{ skill.slug }}</code>
          </div>
          <div class="skill-hub-actions">
            <a
              class="action-btn skill-hub-registry"
              :href="clawhubSkillUrl(skill.slug)"
              rel="noopener noreferrer"
              target="_blank"
              :title="ui.skillsClawHubOpen"
            >
              ClawHub
            </a>
            <button
              class="action-btn copy-btn"
              :class="{ copied: copiedSkillSlug === skill.slug }"
              :title="copiedSkillSlug === skill.slug ? ui.skillsCopied : curlTitle(skill.slug)"
              @click="emit('copySkillLink', skill.slug)"
            >
              {{ copiedSkillSlug === skill.slug ? ui.skillsCopied : ui.skillsCopy }}
            </button>
            <button
              class="action-btn read-btn"
              :class="{ active: expandedSkillSlug === skill.slug }"
              :title="expandedSkillSlug === skill.slug ? ui.skillsCollapse : ui.skillsReadOpen"
              @click="emit('toggleSkill', skill.slug)"
            >
              {{ expandedSkillSlug === skill.slug ? ui.skillsReadClose : ui.skillsReadOpen }}
            </button>
          </div>
        </div>

        <div v-if="expandedSkillSlug === skill.slug" class="doc-reader">
          <div v-if="skillLoading[skill.slug]" class="reader-status">{{ ui.skillsLoading }}</div>
          <div v-else-if="skillError[skill.slug]" class="reader-status err">{{ skillError[skill.slug] }}</div>
          <div v-else class="markdown-body" v-html="skillContent[skill.slug]" />
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.doc-empty { display: flex; flex-direction: column; align-items: center; gap: 0.4rem; padding: 2.5rem 1rem; color: var(--muted, #5c5c5c); font-size: var(--text-ui); }
.doc-empty-icon { width: 2rem; height: 2rem; opacity: 0.4; }
.doc-list { list-style: none; margin: 0; padding: 0; }
.doc-item { border-bottom: 1px solid var(--border, rgba(0, 0, 0, 0.06)); }
.doc-item:last-child { border-bottom: none; }
.skill-item .skill-hub { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 1rem; padding: 1.15rem 1.35rem 1rem; }
.skill-hub-main { flex: 1; min-width: min(100%, 14rem); display: flex; flex-direction: column; gap: 0.45rem; }
.skill-hub-title-row { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.5rem 0.75rem; }
.skill-hub-name { margin: 0; font-size: var(--text-body-lg); font-weight: 600; letter-spacing: -0.02em; line-height: 1.25; }
.skill-hub-version { font-size: var(--text-meta); font-weight: 600; color: var(--muted, #5c5c5c); padding: 0.12rem 0.45rem; border-radius: var(--radius-pill); border: 1px solid var(--border, rgba(0, 0, 0, 0.12)); background: rgba(0, 0, 0, 0.025); }
.skill-hub-summary { margin: 0; font-size: var(--text-ui); line-height: 1.55; color: var(--muted, #5c5c5c); max-width: 48rem; }
.skill-hub-tags { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.skill-hub-tag { font-size: var(--text-meta); font-weight: 500; padding: 0.15rem 0.45rem; border-radius: var(--radius-sm); background: rgba(0, 0, 0, 0.05); color: var(--muted, #5c5c5c); }
.skill-hub-slug { font-size: var(--text-meta); font-family: "SF Mono", ui-monospace, Consolas, monospace; color: var(--muted, #5c5c5c); background: rgba(0, 0, 0, 0.04); padding: 0.2rem 0.45rem; border-radius: var(--radius-sm); align-self: flex-start; }
.skill-hub-actions { display: flex; flex-wrap: wrap; gap: 0.4rem; flex-shrink: 0; align-items: center; }
.skill-hub-registry { font-weight: 600; }
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
</style>
