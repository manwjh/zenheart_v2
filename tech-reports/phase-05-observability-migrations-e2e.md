# Phase 05 — 可观测性、迁移与黑盒测试

> **全量索引**：[backend-code-index.md](backend-code-index.md) 枚举 `v2/backend` 全部 **66** 个 `.py`。

范围：`agent_event_logs` 写入与脱敏、schema 迁移入口、仓库根 `tests/` E2E  harness；**不**展开每条业务幂等策略（当前代码以「帧级错误 + DB 约束」为主，无统一 idempotency key 层）。

---

## 1. 相关文件索引

| 路径 | 职责 |
|------|------|
| `v2/backend/app/services/agent_event_log.py` | `record_agent_event` → 表 `agent_event_logs` |
| `v2/backend/app/event_detail.py` | `sanitize_detail`：键名含 `token`/`password`/`secret`/… → `[redacted]`；字符串截断 |
| `v2/backend/app/models.py` | `AgentEventLog` |
| `v2/backend/app/db.py` | `init_db`：`Base.metadata.create_all`（**非**迁移替代物） |
| `v2/backend/scripts/run_migrations.py` | 对 `DATABASE_URL` 执行 `scripts/migrations/*.sql`（asyncpg） |
| `v2/backend/scripts/migrations/*.sql` | PostgreSQL 增量 DDL |
| `v2/deploy-backend.sh` | 远程重启前调用 `run_migrations.py` |
| `tests/e2e_00_test_lib.py` | HTTP + WS 辅助 |
| `tests/e2e_01_session_bundle.py` ~ `e2e_08_run_decoupled_e2e.py` | 会话、prep、编排 |
| `tests/e2e_04_admin_full.py` | L0 HTTP + WS admin 场景库 |
| `tests/e2e_05_a2a_full_test.py` | A2A + admin 经典套件 CLI |
| `tests/e2e_07_a2a_plan_runner.py` | 覆盖计划表 |
| `tests/e2e_90_smoke_test.py` | 快速冒烟 CLI |
| `tests/e2e_92_db_accounts.py` | DB `seed-e2e` 等 |
| `tests/e2e-test-suite_GUIDE.md` | 链路与模块映射（权威运行说明） |

---

## 2. `AgentEventLog`

| 列 | 类型要点 |
|----|----------|
| `agent_id` | 可空（如握手前失败） |
| `connection_id` | WS 连接 UUID 字符串 |
| `event` | 自由字符串，如 `ws_connected`、`auth_invalid_token`、`a2a_room_created` |
| `detail` | JSONB；写入前 `sanitize_detail` |

**失败策略**：`record_agent_event` 内部 `try/except` 吞掉持久化异常并打日志，**不**向调用方抛（避免影响主路径）。

---

## 3. 典型 `event` 名（非穷尽）

- **鉴权 / WS**：`auth_timeout`、`auth_fail` 类记录见 `ws_auth`；`ws_message_in`、`ws_message_out`、`ws_rate_limit_exceeded`、`ws_disconnected`、`ws_superseded`
- **A2A**：`a2a_ws_connected`、`a2a_ws_disconnected`、`a2a_room_created`、`a2a_room_joined`、`a2a_room_left`、`a2a_room_disconnected`、`a2a_room_dissolved`
- **管理**：`admin_command_*`、`admin_rotate_token_via_ws`、`admin_force_disconnect`（含公开 token reset 理由）
- **内容**：`comment_submitted_via_ws`、`comment_approved_via_ws` 等（`ws_comment_ops`）

完整集合以 `grep record_agent_event v2/backend/app` 为准。

---

## 4. 数据库迁移

- **开发启动**：`create_all` 保证 ORM 已知表存在；**不**应用 `scripts/migrations` 中的历史补丁。
- **部署**：`deploy-backend.sh` 在远程 `systemctl restart` 前执行 `run_migrations.py scripts/migrations`。
- **约束**：`run_migrations.py` 对非 PostgreSQL URL 跳过（打印 skip）。

---

## 5. E2E 测试（`tests/`）

- **位置**：仅仓库根 `tests/`，`v2/backend/scripts/` **无** E2E 包装入口（见 `e2e-test-suite_GUIDE.md`）。
- **依赖**：`--base-url` 指向目标环境；部分链需 **同一 DB** 上 `e2e_92_db_accounts.py seed-e2e`。
- **模块编号**：00 lib；01 bundle；02 DB formal 插入；03 prep CLI；04 admin 库；05 A2A 全量 CLI；06 smoke 多账号库；07 plan runner；08 解耦编排；90 冒烟；92 DB 账号工具。

**凭证文件**：`tests/e2e_accounts.json`、`run_session_accounts.json` 等 **gitignore**，勿提交。

---

## 6. 幂等与重复请求（现状）

- **`dispatch_command_and_wait`**：同一 `(agent_id, request_id)` 并发重复注册 future 会 `RuntimeError duplicate_request_id`（`ws_registry.py`）。
- **业务 WS 帧**：普遍**无**客户端 `idempotency-key` 字段；依赖 DB 唯一约束与 handler 内校验。
- **积分**：`points_service` 内含日 cap 等逻辑（详见该文件）。

---

## 7. 部署

本报告目录不参与服务器同步；见 [README](README.md)。
