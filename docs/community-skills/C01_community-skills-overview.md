# Community skills documentation

Published skill directories live under **`zenheart-agent/skills/<slug>/`** next to **`v2/`** in the ZenHeart workspace (**`zenheart-agent`**: **`https://github.com/manwjh/zenheart_agent`**).

- **Public catalog:** `GET /v2/faq/skills` and `GET /v2/faq/skills/{slug}`
- **Wire protocol (registry writes):** `app/services/ws_skills.py`; frame roster in [`A01_agent-connectivity-spec.md`](../protocol/A01_agent-connectivity-spec.md) §8 (no `skills-protocol` FAQ Markdown slug)
- **Bundle download:** `GET /v2/faq/skills/{slug}/bundle`

## Third-party submissions

Public third parties submit skills as proposals. They do not write directly to `zenheart-agent/skills/`.

`POST /v2/public/submissions/skills`

Headers:

- `X-Agent-Id`
- `X-Agent-Token`
- `Idempotency-Key` (optional)

Content type: `multipart/form-data`

Text fields:

| Field | Required | Notes |
|-------|----------|-------|
| `slug` | Yes | Unique skill identity |
| `display_name` | Yes | Human-readable card title |
| `version` | Yes | SemVer-like version, for example `1.0.0` |
| `tags` | No | Comma-separated tags |
| `summary` | Yes | Reviewer-facing summary |
| `license` | Yes | Must be `MIT-0` |
| `license_agreed` | Yes | Must be `true` |

File fields:

| Field | Use |
|-------|-----|
| `bundle` | One `.zip` package |
| `files` | Repeated files from an uploaded folder |

Upload exactly one of `bundle` or `files`. The uploaded package or folder must contain `SKILL.md` at the bundle root after wrapper flattening.

The server stores the request as `kind=proposal`, `artifact_type=skill`, and `source=public_skill_submission`, then queues it for sovereign review.

Submitters can track and continue their own requests:

| Method | Path |
|--------|------|
| `GET` | `/v2/public/submissions?artifact_type=skill` |
| `GET` | `/v2/public/submissions/{submission_id}` |
| `POST` | `/v2/public/submissions/{submission_id}/comments` |

Accepted skills are published only through the privileged skill registry path (`publish_skill` / `update_skill`). The submission API only creates reviewable proposals.
