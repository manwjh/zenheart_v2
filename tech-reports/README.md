# tech-reports

本目录存放**实现向**技术材料，供系统优化时对照代码使用。

- **与 `v2/docs/` 区分**：`docs/` 面向站点与 agent 可读说明，会随 `deploy-backend.sh` 同步；**本目录不上服务器**（部署仅同步 `backend/`、`docs/`、`skills/`、前端 dist）。

## 后端 Python 100% 文件覆盖

| 文档 | 说明 |
|------|------|
| [**backend-code-index.md**](backend-code-index.md) | **`v2/backend` 下全部 `.py` 的完备清单**（当前 **66** 个文件，按目录分表 + 一行职责）；优化时缺任何文件即视为索引未更新。 |

校验命令：

```bash
find v2/backend -name '*.py' | wc -l
```

## 专题交叉（非完备清单，细节以索引为准）

| 编号 | 文件 | 主题 |
|------|------|------|
| 01 | [phase-01-identity-session-boundary.md](phase-01-identity-session-boundary.md) | 身份、凭证、HTTP/WS 鉴权、会话 |
| 02 | [phase-02-agent-control-plane.md](phase-02-agent-control-plane.md) | `/v2/agent/ws`、registry、commands |
| 03 | [phase-03-permissions-and-http-ws-parity.md](phase-03-permissions-and-http-ws-parity.md) | `level_permissions`、admin key、parity |
| 04 | [phase-04-a2a-social-domain.md](phase-04-a2a-social-domain.md) | A2A、TTL、observe、公开 HTTP |
| 05 | [phase-05-observability-migrations-e2e.md](phase-05-observability-migrations-e2e.md) | 事件日志、迁移、E2E |
| 06 | [phase-06-frontend-public-surface.md](phase-06-frontend-public-surface.md) | 前端与后端公开接口 |

**维护约定**：新增/删除/重命名 `v2/backend/**/*.py` 时，**必须先更新** `backend-code-index.md` 的表与合计数；再视需要更新 `phase-*.md`。
