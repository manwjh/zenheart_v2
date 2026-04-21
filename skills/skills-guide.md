# Skills Guide

This directory hosts Cursor Agent Skills published by ZenHeart. Each skill is a reusable behavior
package that any Cursor-based agent can download and activate.

---

## What is a Skill?

A Cursor Agent Skill is a `SKILL.md` file that teaches an agent a specific, repeatable task.
When an agent reads a skill file, it gains the instructions, context, and tool-use patterns
needed to perform that task without further human guidance.

Skills in this directory are packaged as `.zip` archives containing at minimum a `SKILL.md`.
The matching `.md` file on this page is the plain-text description you can paste directly into
any AI coding tool — it will fetch and read the skill on its own.

---

## How to Use a Skill

### Option A — reference the raw URL

Paste the raw markdown URL into your agent prompt or Cursor chat:

```
https://www.zenheart.net/v2/faq/skills/<slug>
```

Cursor will fetch the content automatically when you include a URL in the context.

### Option B — download and install locally

1. Download the `.zip` from this page.
2. Unzip to `~/.cursor/skills-cursor/<skill-name>/`.
3. The skill is now available to your local Cursor agent.

---

## Skill File Conventions

Each skill package must follow this layout:

```
<skill-name>/
  SKILL.md          required — instructions the agent reads at runtime
  README.md         optional — human-readable background and examples
  scripts/          optional — helper scripts referenced by SKILL.md
```

The `SKILL.md` first line must be a level-1 heading (`# Skill Name`) used as the display title.

---

## Publishing a New Skill

To add a skill to this directory, place two files in `v2/skills/` with the same base name:

| File | Purpose |
|------|---------|
| `<slug>.md` | Description shown on the FAQ page (this file's format) |
| `<slug>.zip` | Downloadable archive containing the skill package |

The FAQ page discovers files automatically — no config change or server restart required.
