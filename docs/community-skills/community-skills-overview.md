# Community skills documentation

Published skill directories live under **`zenheart-agent/skills/<slug>/`** next to **`v2/`** in the ZenHeart workspace (**`zenheart-agent`**: **`https://github.com/manwjh/zenheart_agent`**).

- **Public catalog:** `GET /v2/faq/skills` and `GET /v2/faq/skills/{slug}`
- **Wire protocol (registry writes):** `app/services/ws_skills.py`; frame roster in [`A01_agent-connectivity-spec.md`](../protocol/A01_agent-connectivity-spec.md) §8 (no `skills-protocol` FAQ Markdown slug)
- **Bundle download:** `GET /v2/faq/skills/{slug}/bundle`
