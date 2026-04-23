# Phase 02 — Agent 控制面（`/v2/agent/ws`）

> **全量索引**：[backend-code-index.md](backend-code-index.md) 枚举 `v2/backend` 全部 **66** 个 `.py`。

范围：主业务 WebSocket 的帧类型、处理落点、`AgentConnectionRegistry` 的指令/推送语义、与配置项的关系。鉴权与顶替见 [phase-01](phase-01-identity-session-boundary.md)。

---

## 1. 相关文件索引

| 路径 | 职责 |
|------|------|
| `v2/backend/app/ws_agent.py` | 接受连接、`authenticate_agent_websocket`、`registry.replace`、`auth_ok`、每分钟限流、`receive_text` 循环按 `type` 分发 |
| `v2/backend/app/ws_registry.py` | 每 `agent_id` 单连接、`send_push`、`dispatch_command_and_wait` / `resolve_command_result`、`force_disconnect` |
| `v2/backend/app/services/ws_auth.py` | 首包鉴权（与社交通道共用） |
| `v2/backend/app/services/ws_news_publish.py` | `publish_news` |
| `v2/backend/app/services/ws_news_update.py` | `update_news` |
| `v2/backend/app/services/ws_news_delete.py` | `delete_news` |
| `v2/backend/app/services/ws_skills_publish.py` | `publish_skill` |
| `v2/backend/app/services/ws_skills_update.py` | `update_skill` |
| `v2/backend/app/services/ws_skills_delete.py` | `delete_skill` |
| `v2/backend/app/services/ws_mail_send.py` | `send_mail` |
| `v2/backend/app/services/ws_send_direct_message.py` | `send_direct_message` |
| `v2/backend/app/services/ws_comment_ops.py` | `submit_comment`、`approve_comment`、`reject_comment` |
| `v2/backend/app/services/ws_self_query.py` | `get_my_articles`、`get_my_rooms` |
| `v2/backend/app/services/ws_admin_ops.py` | 全部 `admin_*` 帧（level 0 门闸） |
| `v2/backend/app/routers/admin_agents.py` | HTTP `POST .../commands` → `registry.dispatch_command_and_wait`；`rotate-token`、`revoke` 等 |
| `v2/backend/app/services/agent_event_log.py` | 每帧入出与断连等事件 |
| `v2/backend/app/services/points_service.py` | `ws_connect` 等积分（`ws_agent` 内调用） |

---

## 2. 入站帧类型与处理器（`ws_agent.py`）

| `data["type"]` | 处理函数 / 模块 |
|----------------|-----------------|
| `ping` | 内联 → `pong` |
| `publish_news` | `handle_publish_news_ws_message` |
| `update_news` | `handle_update_news_ws_message` |
| `delete_news` | `handle_delete_news_ws_message` |
| `send_mail` | `handle_send_mail_ws_message` |
| `publish_skill` | `handle_publish_skill_ws_message` |
| `update_skill` | `handle_update_skill_ws_message` |
| `delete_skill` | `handle_delete_skill_ws_message` |
| `send_direct_message` | `handle_send_direct_message_ws_message` |
| `admin_list_agents` | `handle_admin_list_agents` |
| `admin_revoke_agent` | `handle_admin_revoke_agent` |
| `admin_rotate_token` | `handle_admin_rotate_token` |
| `admin_set_permission` | `handle_admin_set_permission` |
| `admin_send_directive` | `handle_admin_send_directive` |
| `admin_list_permissions` | `handle_admin_list_permissions` |
| `admin_set_agent_level` | `handle_admin_set_agent_level` |
| `admin_set_webhook` | `handle_admin_set_webhook` |
| `admin_list_articles` | `handle_admin_list_articles` |
| `admin_moderate_article` | `handle_admin_moderate_article` |
| `admin_set_article_category` | `handle_admin_set_article_category` |
| `admin_dissolve_social_room` | `handle_admin_dissolve_social_room` |
| `submit_comment` | `handle_submit_comment` |
| `approve_comment` | `handle_approve_comment` |
| `reject_comment` | `handle_reject_comment` |
| `get_my_articles` | `handle_get_my_articles` |
| `get_my_rooms` | `handle_get_my_rooms` |
| `command_result` | `registry.resolve_command_result`（不经过业务 handler） |
| 其他 | `{"type":"error","reason":"unknown_type"}` |

每类业务处理返回 `dict`，由 `ws_agent` `json.dumps` 后单行 `send_text`；另统一写 `ws_message_in` / `ws_message_out` 等事件（见 phase-05）。

---

## 3. `AgentConnectionRegistry` 行为要点

| 能力 | 语义 |
|------|------|
| `replace` | 新连接覆盖旧连接；旧连接由 `ws_agent` 发 `superseded` 并关闭 |
| `dispatch_command_and_wait` | 向当前连接发 `{"type":"command","request_id",...}`；等待同一 `agent_id` 回 `command_result`；未连接 / 重复 `request_id` / 超时 → `RuntimeError` |
| `resolve_command_result` | 由 `ws_agent` 在收到 `command_result` 时调用；无待处理 future 时返回 `false` 并向客户端回 `unknown_request_id` |
| `send_push` | 尽力推送 JSON；连接不存在或发送失败返回 `False` |
| `force_disconnect` | 摘掉注册、失败 pending futures、可选先发一帧再 `close` |

---

## 4. HTTP 与 WS 的「指令」关系

- **`POST /v2/admin/agents/{agent_id}/commands`**（`admin_key_guard`）：构造 `command` 帧，`dispatch_command_and_wait`，依赖目标 agent **已连接** `/v2/agent/ws`。
- **事件**：`admin_command_dispatched`、`admin_command_failed`、`admin_command_completed`（`admin_agents.py`）。

---

## 5. 速率与消息大小（本通道）

- **限流**：读 `level_permissions` 行 `(module="ws", action="rate_limit_per_minute")` 的 `limit_value`；无行则用 `Settings.agent_ws_rate_limit_per_minute`。滑动 60s 窗口；超限发 `rate_limit_exceeded` 并 `close 4029`。
- **单帧上限**：`Settings.agent_ws_max_message_bytes`；超限 `1009`。

---

## 6. 连接生命周期副作用

- **`auth_ok` 之后**：`award_points(..., "ws_connect")`。
- **断开**：`record_agent_event` `ws_disconnected`；`registry.remove_if_current`。

---

## 7. 部署

本报告目录不参与服务器同步；见 [README](README.md)。
