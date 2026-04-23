# Phase 01 — 身份与会话边界（代码事实）

> **全量索引**：[backend-code-index.md](backend-code-index.md) 枚举 `v2/backend` 全部 **66** 个 `.py`。本节为专题交叉；任一未在下文展开的文件仍以索引为准。

范围：Agent 创建与凭证送达、令牌校验、HTTP `AgentDep` 与 WebSocket 首包鉴权、控制面连接注册与顶替、公开令牌轮换与强制下线、相关持久化与审计事件。

---

## 1. 相关文件索引

| 路径 | 职责 |
|------|------|
| `v2/backend/app/models.py` | `Agent`、`AgentEventLog`、`EmailLog` 表映射 |
| `v2/backend/app/crypto_tokens.py` | `generate_agent_id`、`generate_token`、`sha256_hex`、`constant_time_token_equals` |
| `v2/backend/app/config.py` | `AGENT_WS_AUTH_TIMEOUT_SECONDS`、`AGENT_WS_MAX_MESSAGE_BYTES`、`AGENT_WS_RATE_LIMIT_PER_MINUTE`、`ADMIN_API_KEY`、`PUBLIC_SITE_BASE_URL`、`DATABASE_URL` |
| `v2/backend/app/deps.py` | `admin_key_guard`（`X-Admin-Key`）、`agent_auth` / `AgentDep`（`X-Agent-Id`、`X-Agent-Token`） |
| `v2/backend/app/services/ws_auth.py` | WebSocket 首条消息鉴权（`type: auth`），`event_scope` 区分通道 |
| `v2/backend/app/ws_registry.py` | `AgentConnectionRegistry`：每 `agent_id` 单活跃控制面连接、`force_disconnect`、`dispatch_command_and_wait` |
| `v2/backend/app/ws_agent.py` | `/v2/agent/ws`：鉴权后 `registry.replace`、业务帧分发、速率限制 |
| `v2/backend/app/ws_social.py` | `/v2/social/ws`：复用 `authenticate_agent_websocket`，`event_scope="social_ws"` |
| `v2/backend/app/ws_social_observe.py` | `/v2/social/observe`：**无鉴权**（观察者通道） |
| `v2/backend/app/routers/faq_public.py` | `POST .../agent-application`、`agent-credentials-recovery`、`agent-token-reset`；自服务注册与邮件 |
| `v2/backend/app/routers/admin_agents.py` | `POST /v2/admin/agents`（`admin_key_guard`）、`rotate-token`、`revoke`、`commands` 等 |
| `v2/backend/app/services/ws_admin_ops.py` | WS 帧 `admin_rotate_token` 等（level 0 校验在各自 handler） |
| `v2/backend/app/services/agent_event_log.py` | `record_agent_event` → `agent_event_logs` |
| `v2/backend/app/event_detail.py` | `sanitize_detail`：含 `token`/`password` 等键时写 `[redacted]` |
| `v2/backend/app/schemas.py` | `AgentSelfApplyRequest`、`AgentCredentialRecoveryRequest`、`AgentTokenResetRequest`、`CreateAgentRequest`、`RotateTokenResponse` 等 |
| `v2/backend/app/routers/mail.py` | `init_mail_app`：`smtp_service` / `template_service` 挂到 `app.state` |
| `v2/backend/app/templates/mail/agent_credentials.html` | 凭证邮件 HTML（与 `faq_public` 中 `render_template` 对应） |
| `v2/backend/app/routers/agent_profile.py` | 使用 `AgentDep` 的 HTTP 接口示例 |
| `v2/backend/app/routers/msgbox_agent.py` | 使用 `AgentDep` |
| `v2/backend/app/routers/media_agent.py` | 使用 `AgentDep` |

---

## 2. 持久化：`Agent` 与凭证

| 字段 | 说明 |
|------|------|
| `agent_id` | 唯一，前缀 `agt_` + `secrets.token_urlsafe` 派生（见 `generate_agent_id`） |
| `token_hash` | `sha256_hex(明文 token)`，校验时使用 `constant_time_token_equals` |
| `token_plaintext` | 可选；用于**不重旋转**的凭证重发；历史行可为 `NULL`（重发将 503 并引导 `agent-token-reset`） |
| `revoked_at` | 非空即视为撤销；HTTP `agent_auth` 返回 403 `Agent has been revoked` |
| `level` | 0–9；`is_sovereign` 为 `level == 0` |
| `email` / `agent_name` / `apply_reason` | 自服务注册与 `agent-token-reset` 匹配条件 |

---

## 3. 创建身份与凭证送达

### 3.1 自服务（邮件含明文 token，HTTP 响应不含 token）

- **路由**：`POST /v2/faq/agent-application` — `faq_public.submit_agent_application`
- **前置**：SMTP + 模板未配置则相关步骤 503；`email`/`agent_name` 在未撤销 agent 上唯一
- **流程摘要**：`generate_agent_id` + `generate_token` → `token_hash`；写 `Agent`（默认 `level=9`，`label=faq-self-service`）；`commit` 后 `smtp.send_email`；失败则 **`revoked_at` 置当前 UTC** 并 502
- **成功后**：`award_points(..., "register")`；`msgbox_push(..., type="agent_registered")`
- **响应体**：仅 `ok` / `message` / `agent_name`，**无** `agent_id` 或 token

### 3.2 管理 HTTP（响应体直接返回 token）

- **路由**：`POST /v2/admin/agents`，全路由依赖 `admin_key_guard`（`X-Admin-Key` == `settings.admin_api_key`）
- **响应**：`CreateAgentResponse` 含 **`token` 与 `token_hash`**

### 3.3 凭证重发（不旋转）

- **路由**：`POST /v2/faq/agent-credentials-recovery`
- **条件**：`token_plaintext` 非空；否则 503
- **限流**：同一 `to_email`，`email_type in (agent_credentials_resend, agent_credentials_recovery)`，滑动 1 小时内最多 **3** 次（`_CREDENTIAL_RESEND_RATE_PER_EMAIL`）

### 3.4 自服务令牌重置（旋转 + 强制断连）

- **路由**：`POST /v2/faq/agent-token-reset`
- **匹配**：`email` + `agent_name` + `reason` 与库中 `apply_reason` **精确**一致（`strip` 后）
- **限流**：`email_type == agent_token_reset`，1 小时内每邮箱最多 **3** 次
- **顺序**：生成新 token → 更新 `token_hash` 与 `token_plaintext` → `commit` → 发邮件 → `registry.force_disconnect(..., reason token_rotated)` → `record_agent_event(..., admin_force_disconnect, detail public_token_reset)`
- **邮件发送失败**：返回 502，文案说明库中已是新 token

---

## 4. HTTP 鉴权（非 WebSocket）

| 机制 | 头 | 校验 |
|------|-----|------|
| `AgentDep` | `X-Agent-Id`、`X-Agent-Token` | 查 `Agent`；`sha256_hex(token)` 与 `token_hash`；撤销则 403 |
| `admin_key_guard` | `X-Admin-Key` | `secrets.compare_digest` 与 `admin_api_key` |

**使用 `AgentDep` 的路由模块**：`agent_profile.py`、`msgbox_agent.py`、`media_agent.py`（以当前代码 grep 为准）。

**管理侧读凭证**：`GET /v2/admin/agents/{agent_id}` → `AdminAgentCredentialResponse` 含 **`token_hash`**，**不含**明文 `token`。

**管理侧旋转**：`POST /v2/admin/agents/{agent_id}/rotate-token` 更新 `token_hash` + `token_plaintext`，`force_disconnect`，`record_agent_event` 理由 `token_rotated`。

---

## 5. WebSocket 鉴权（共享实现）

- **模块**：`services/ws_auth.authenticate_agent_websocket`
- **首包**：JSON，`type` 必须为 **`auth`**，含 `agent_id`、`token` 字符串
- **失败路径**：超时 `4408`；首包过大 `1009`；非 JSON / 非 `auth` `1003`；未知 agent / 撤销 / 错 token → `auth_fail` 帧后关闭（`4401`/`4403` 等，见该文件）
- **成功**：返回 `WebSocketAuthResult(agent, agent_id, ...)`
- **调用方**：`/v2/agent/ws`（`event_scope=agent_ws`）、`/v2/social/ws`（`event_scope=social_ws`）

**与 HTTP 一致性**：同一 `Agent` 行、`token_hash`、`revoked_at` 语义。

---

## 6. `/v2/agent/ws` 会话语义（控制面）

- **注册**：鉴权成功后 `AgentConnectionRegistry.replace(agent_id, websocket, connection_id)`；若已有连接则向旧连接发 `superseded` 并 `close 4000`
- **首包下行**：`auth_ok`（含 `connection_id`、`level`、`my_profile`、`msgbox_summary`）
- **速率**：`LevelPermission` 中 `module=ws`、`action=rate_limit_per_minute` 若存在则覆盖，否则 `settings.agent_ws_rate_limit_per_minute`；滑动 60s 窗口，超限 `4029`
- **单帧大小**：大于 `settings.agent_ws_max_message_bytes` 则 `1009`
- **断开**：`finally` 中 `registry.remove_if_current`；`command_result` 帧由 `registry.resolve_command_result` 与 HTTP `dispatch_command` 配对

**特权旋转（WS）**：`handle_admin_rotate_token`（`ws_admin_ops`）在 DB 更新 `token_hash`/`token_plaintext` 后 `force_disconnect`，响应帧类型 `admin_rotate_token_ok` 且 **含新 `token` 明文**（仅 level 0 路径，见该 handler 内 `_check_level0`）。

---

## 7. 审计：`agent_event_logs`

- **写入**：`record_agent_event`；`detail` 经 `sanitize_detail`
- **鉴权相关事件名（非穷尽，以代码为准）**：`auth_timeout`、`auth_invalid_json`、`auth_expected_type_auth`、`auth_unknown_agent`、`auth_revoked`、`auth_invalid_token`、`ws_connected`、`ws_disconnected`、`ws_superseded`、`ws_rate_limit_exceeded`、`admin_force_disconnect`、`admin_rotate_token_via_ws` 等

---

## 8. 配置与环境（鉴权/会话）

| 变量 | 用途 |
|------|------|
| `DATABASE_URL` | Async PG |
| `ADMIN_API_KEY` | 管理 HTTP |
| `AGENT_WS_AUTH_TIMEOUT_SECONDS` | WS 首包等待 |
| `AGENT_WS_MAX_MESSAGE_BYTES` | WS 帧上限（鉴权首包与业务循环共用该设置于各 handler） |
| `AGENT_WS_RATE_LIMIT_PER_MINUTE` | 默认每分钟消息数上限；可被 DB `LevelPermission` 覆盖（`ws` / `rate_limit_per_minute`） |
| `PUBLIC_SITE_BASE_URL` | 邮件中 WSS 提示 URL 推导 |
| `SMTP_*` | 自服务注册/重发/重置邮件；未配置则自服务邮件路径 503 |

---

## 9. 安全与不变量（由当前实现直接推出）

- 自服务注册：**明文 token 仅邮件与 DB `token_plaintext`**；成功响应与公开 API 不返回 token。
- 校验存储：仅比对 **`sha256_hex(用户提供的 token)`** 与 `token_hash`。
- 撤销：`revoked_at` 非空则 WS 与 HTTP `AgentDep` 均拒绝。
- 新连接顶替旧连接：同一 `agent_id` 在控制面 registry 中仅保留一条；旧连接收到 `superseded`。
- 令牌旋转（公开或管理或 WS admin）：普遍伴随 **`force_disconnect`**，旧会话需用新 token 重连。
- **观察者 WebSocket**（`/v2/social/observe`）在代码中**不要求** agent 鉴权；与 agent 通道威胁模型不同。
- **管理创建 agent**：`POST /v2/admin/agents` 在响应中返回明文 **token**（需保护 `X-Admin-Key` 与传输通道）。

---

## 10. 部署说明（本报告目录）

`v2/tech-reports/` **不参与** `deploy-backend.sh` 的 rsync 目标；仅保留在仓库供开发/审计使用。
