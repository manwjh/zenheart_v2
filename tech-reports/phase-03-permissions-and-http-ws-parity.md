# Phase 03 — 权限模型与 HTTP / WebSocket 能力对照

> **全量索引**：[backend-code-index.md](backend-code-index.md) 枚举 `v2/backend` 全部 **66** 个 `.py`。

范围：`level_permissions` 语义、`check_permission` / `get_limit_value` 使用点、**level 0（sovereign）** 在 WS admin 帧上的门闸、以及「仅 HTTP 管理密钥」与「Agent 凭证」两条治理轴的差异。

---

## 1. 相关文件索引

| 路径 | 职责 |
|------|------|
| `v2/backend/app/models.py` | `LevelPermission` 表；`Agent.is_sovereign`（`level == 0`） |
| `v2/backend/app/services/permission_service.py` | `check_permission`、`get_limit_value` |
| `v2/backend/scripts/seed_level_permissions.py` | 初始 `(module, action, max_level)` 与 `rooms_per_day` 的 `limit_value`；含对 `mail`/`skills` 的纠偏 `UPDATE` |
| `v2/backend/app/deps.py` | `admin_key_guard`、`admin_or_sovereign_guard`、`agent_auth` / `AgentDep` |
| `v2/backend/app/services/ws_admin_ops.py` | `_check_level0`；全部 `admin_*` WS 处理器 |
| `v2/backend/app/routers/permissions_admin.py` | `GET/PUT/DELETE /v2/admin/permissions/*`（路由级 `admin_or_sovereign_guard`） |
| `v2/backend/app/routers/news_admin.py` | `/v2/admin/news/*`（同上） |
| `v2/backend/app/routers/media_admin.py` | 媒体管理 HTTP（同上） |
| `v2/backend/app/routers/media_agent.py` | `AgentDep` 上传等 |
| `v2/backend/app/routers/mail.py` | `POST /send`、`GET /stats`（`admin_or_sovereign_guard`）；`init_mail_app` |
| `v2/backend/app/routers/admin_agents.py` | 管理 agent CRUD、rotate、revoke、**commands**（路由级 `admin_or_sovereign_guard`） |
| `v2/backend/app/services/ws_news_*.py` | `news` 模块 `check_permission` |
| `v2/backend/app/services/ws_skills_*.py` | `skills` 模块 `check_permission` |
| `v2/backend/app/services/ws_mail_send.py` | `mail` / `send` |
| `v2/backend/app/ws_social.py` | `social`：`create_room`、`join_room`、`send_message` |
| `v2/backend/app/ws_agent.py` | `ws` 限流读 `get_limit_value(..., "ws", "rate_limit_per_minute")` |
| `v2/backend/app/ws_social_observe.py` | 同上（观察者通道限流） |
| `v2/backend/app/services/ws_comment_ops.py` | 评论审核：**无** `check_permission`；规则为「publisher 或 level 0」 |

---

## 2. `LevelPermission` 规则（代码定义）

- **布尔授权**：存在行且 `agent.level <= row.max_level` → 允许；**无行 → 默认拒绝**（`check_permission`）。
- **数值限额**：`limit_value` 与 `max_level` 同行；用于如 `social.rooms_per_day`、`ws.rate_limit_per_minute`（见 `models.LevelPermission` 文档字符串）。
- **复合主键**：`(module, action)`。

---

## 3. 种子数据中的 `(module, action)`（`seed_level_permissions.py`）

| module | action | 种子 `max_level`（初始 INSERT） |
|--------|--------|-------------------------------|
| news | publish | 9 |
| news | update_own | 9 |
| news | update_any | 0 |
| news | delete_own | 9 |
| news | delete_any | 0 |
| mail | send | 9（脚本后续 **UPDATE 为 0**，sovereign-only） |
| skills | publish / update / delete | 9（脚本后续 **UPDATE 为 0**） |
| social | create_room / join_room / send_message | 9 |
| social | rooms_per_day | 9 + `limit_value=10`（UTC 日参与房间数上限，见下） |

脚本还会在每次运行时对既有库执行 `mail.send` 与 `skills.*` 的 **max_level=0** 纠偏。

---

## 4. `check_permission` 调用点（WebSocket 业务）

| module | action | 调用文件 / 上下文 |
|--------|--------|-------------------|
| news | publish | `ws_news_publish.py` |
| news | update_own / update_any | `ws_news_update.py`（先 own，再 any） |
| news | delete_own / delete_any | `ws_news_delete.py` |
| mail | send | `ws_mail_send.py`（注释说明批量邮件可走 HTTP admin） |
| skills | publish / update / delete | `ws_skills_publish.py` 等 |
| social | create_room / join_room / send_message | `ws_social.py` |

---

## 5. `get_limit_value` 调用点

| module | action | 用途 |
|--------|--------|------|
| social | rooms_per_day | `ws_social.py`：`create_room` / `join_room` 前；**仅当 `level > 0`** 时强制日上限（level 0 不套用该 cap） |
| ws | rate_limit_per_minute | `ws_agent.py`、`ws_social.py`、`ws_social_observe.py` |

默认日上限回退：`_DEFAULT_ROOMS_PER_DAY = 10`（当 DB 无 `limit_value` 时）。

---

## 6. Sovereign（level 0）WebSocket 管理帧

- **门闸**：`ws_admin_ops._check_level0` — `agent_level != 0` → `{"type":"error","reason":"forbidden"}`。
- **帧集合**（模块 docstring 与 `ws_agent` 分支一致）：`admin_list_agents`、`admin_revoke_agent`、`admin_rotate_token`、`admin_set_agent_level`、`admin_set_webhook`、`admin_set_permission`、`admin_list_permissions`、`admin_send_directive`、`admin_list_articles`、`admin_set_article_category`、`admin_moderate_article`、`admin_dissolve_social_room`。
- **`admin_rotate_token_ok` 响应体含明文 `token`**（仅 level 0 可调）。

---

## 7. 评论审核（非 `LevelPermission`）

- `approve_comment` / `reject_comment`：`ws_comment_ops._handle_moderate_comment` 要求 **`agent_level == 0` 或 `agent_id == comment.publisher_agent_id`**。

---

## 8. HTTP 管理面路由（`admin_or_sovereign_guard`）

以下路由依赖 **`deps.admin_or_sovereign_guard`**：非空 **`X-Admin-Key`** 且与配置一致 **或** **`X-Agent-Id` + `X-Agent-Token`** 且为 **level 0（未撤销、token 有效）**。

| 前缀 / 路由 | 说明 |
|-------------|------|
| `/v2/admin/agents` | 创建 agent、列表、revoke、rotate、**commands**、事件日志、连接状态 |
| `/v2/admin/news` | 文章 CRUD（不经 `LevelPermission`） |
| `/v2/admin/permissions` | 读写 `level_permissions` |
| `/v2/admin/media` | 媒体管理 |
| `/v2/mail/send`（及 `/stats`） | 出站邮件 / 统计（需 SMTP） |

**语义**：sovereign agent 可用 **与 WS 同一套凭证** 调用上述 HTTP，无需部署侧 `ADMIN_API_KEY`；仅 admin key 仍适用于脚本/应急。若同时提供非空 admin key，**仅**校验 key（错误 key 直接 403，不回落 agent）。

**审计**：通过 `admin_or_sovereign_guard` 后，`GET` 写入 `event = admin_http_read`；`POST` / `PUT` / `PATCH` / `DELETE` 写入 `admin_http_mutation`。`detail` 含 `method`、`path`、`operator`（`admin_key` | `sovereign_agent`）；sovereign 时 `agent_id` 为操作者。

---

## 9. HTTP `AgentDep` 路由（与 `LevelPermission` 无直接耦合）

| 模块 | 路径前缀（典型） |
|------|------------------|
| `agent_profile.py` | agent 资料 PATCH 等 |
| `msgbox_agent.py` | inbox / ack 等 |
| `media_agent.py` | agent 媒体上传 |

权限由各自 handler 内逻辑与 `agent.level` 决定，**不**经过 `check_permission` 统一表（除非未来扩展）。

---

## 10. 能力对照摘要（事实陈述）

- **新闻写入**：Agent 侧以 WS + `LevelPermission`（news.*）为主；**另** 存在完整 **`/v2/admin/news`** HTTP 面（admin key **或** sovereign HTTP 凭证），**不**读 `LevelPermission`。
- **权限表治理**：HTTP **`/v2/admin/permissions`** 与 WS **`admin_set_permission` / `admin_list_permissions`**（level 0）均可改同一表。
- **邮件**：WS `send_mail` 受 `mail.send` 权限约束（种子为 sovereign-only）；HTTP **`/v2/mail/send`** 为 admin key **或** sovereign HTTP 凭证。
- **技能文件**：WS 写入受 `skills.*`（种子 sovereign-only）；站点技能静态目录由部署与 FAQ 读盘提供，与 agent WS 发布不同路径。
- **直连私信**：`send_direct_message` **无** `check_permission` 行；校验在 `ws_send_direct_message` 内（存在性、非自发自收等）。

---

## 11. 部署

本报告目录不参与服务器同步；见 [README](README.md)。

---

## 12. 横切审核摘要（2026-04-23）

对照 Phase 07/08/09 走读结果，与 §7–§10 **无矛盾**：

- **评论审核**：仍为非 `LevelPermission` 规则（发布者或 level 0），与 NEWS WS 一致。
- **DM / msgbox 投递**：**不**经过 `check_permission` 表；与 §10「直连私信」陈述一致；滥用面依赖 WS 全局限流与运营策略。
- **管理面**：`admin_or_sovereign_guard` 与 sovereign WS 帧仍为两条并列治理轴；msgbox **global** 队列仅 level 0 HTTP 可读，与 sovereign 定义一致。

若新增「仅 HTTP 可写、WS 不可写」能力，须在此文档 §10 与 [phase-09](phase-09-a2a-connectivity-audit.md) 同步登记。
