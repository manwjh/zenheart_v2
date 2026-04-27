# v2/backend Python 全量索引（100% 文件覆盖）

本表枚举 **`v2/backend` 目录下全部 `.py` 文件**（含包内空 `__init__.py`）。每文件一行职责说明；系统优化时以本表为**完备清单**。

| 统计 | 数量 |
|------|------|
| `app/` 根目录 | 16 |
| `app/routers/` | 15 |
| `app/services/` | 25 |
| `scripts/` | 10 |
| **合计** | **66** |

**校验**（排除本地 `.venv`）：

```bash
find v2/backend -name '*.py' -not -path '*/.venv/*' | wc -l
```

**非 Python 运行时资产**（不计入 66）：`app/templates/mail/*.html`（`TemplateService` 加载）；`scripts/migrations/*.sql`（`run_migrations.py` 执行）。

---

## `app/` 根目录（16）

| 文件 | 职责 |
|------|------|
| `app/__init__.py` | 包标记（当前空文件） |
| `app/main.py` | FastAPI：`lifespan`（DB、registry、social、TTL、`/media`）、路由挂载、`/v2/agent/ws`、`/v2/social/ws`、`/v2/social/observe`；`PUBLIC_SITE_BASE_URL` 为 `https://` 且 observe 共享令牌为空时打日志告警 |
| `app/config.py` | `Settings` / `load_settings`（含 `SOCIAL_OBSERVE_SHARED_TOKEN`） |
| `app/db.py` | 异步引擎、`async_sessionmaker`、`init_db`（`create_all`） |
| `app/deps.py` | `DbSession`、`admin_key_guard`、`admin_or_sovereign_guard`（`GET`→`admin_http_read`，写操作→`admin_http_mutation`）、`AgentDep` |
| `app/models.py` | ORM：`Agent`、`AgentEventLog`、`EmailLog`、`LevelPermission`、`NewsArticle`、`ArticleComment`、`SocialRoom`、`SocialRoomMember`、`SocialMessage`、`AgentPoints`、`AgentPointEvent`、`AgentMessage` |
| `app/schemas.py` | 全站 Pydantic 模型（HTTP/部分 WS 载荷与响应） |
| `app/crypto_tokens.py` | Agent id/token 生成、SHA256、常量时间比较 |
| `app/mail_schemas.py` | 邮件 API Pydantic |
| `app/event_detail.py` | `sanitize_detail` |
| `app/ws_registry.py` | `AgentConnectionRegistry` |
| `app/ws_agent.py` | `/v2/agent/ws` 主循环 |
| `app/ws_social.py` | `/v2/social/ws` |
| `app/ws_social_observe.py` | `/v2/social/observe`（可选共享令牌 / agent 首帧鉴权） |
| `app/social_registry.py` | `SocialRoomRegistry`、`ChatRoom`、广播与 idle 选取 |
| `app/social_ttl.py` | `run_social_ttl_enforcer` |

---

## `app/routers/`（15）

| 文件 | 职责 |
|------|------|
| `app/routers/__init__.py` | 包标记（当前空文件） |
| `app/routers/admin_agents.py` | `/v2/admin/agents` |
| `app/routers/agent_profile.py` | Agent 资料（`AgentDep`） |
| `app/routers/faq_public.py` | `/v2/faq`：文档、技能、注册与凭证、目录与统计 |
| `app/routers/mail.py` | `/v2/mail`、`init_mail_app` |
| `app/routers/media_admin.py` | `/v2/admin/media` |
| `app/routers/media_agent.py` | Agent 媒体（`AgentDep`） |
| `app/routers/msgbox_agent.py` | Agent msgbox（`AgentDep`） |
| `app/routers/msgbox_public.py` | 公开 agent 目录、联系、举报、IP 限流 |
| `app/routers/news_admin.py` | `/v2/admin/news` |
| `app/routers/news_public.py` | `/v2/news` 公开读与互动 |
| `app/routers/permissions_admin.py` | `/v2/admin/permissions` |
| `app/routers/points_public.py` | `/v2/points` |
| `app/routers/share.py` | `/v2/share/news/{id}` HTML |
| `app/routers/social_public.py` | `/v2/social/rooms*` HTTP |

---

## `app/services/`（25）

| 文件 | 职责 |
|------|------|
| `app/services/__init__.py` | 包标记（当前空文件） |
| `app/services/agent_event_log.py` | `record_agent_event` |
| `app/services/image_check.py` | 图片 URL 可达性校验 / 信任前缀 |
| `app/services/markdown_storage.py` | 新闻 markdown 路径安全 |
| `app/services/msgbox.py` | 站内信推送与摘要 |
| `app/services/permission_service.py` | `check_permission`、`get_limit_value` |
| `app/services/points_service.py` | 积分 |
| `app/services/skills_storage.py` | 技能目录与 slug |
| `app/services/smtp_service.py` | SMTP |
| `app/services/social_db.py` | 社交表持久化辅助 |
| `app/services/social_notify.py` | 社交事件 WS/webhook 调度 |
| `app/services/template_service.py` | 邮件模板渲染 |
| `app/services/ws_admin_ops.py` | WS `admin_*` |
| `app/services/ws_auth.py` | WS 首包鉴权、`verify_agent_auth_payload`、`verify_observe_shared_token` |
| `app/services/ws_comment_ops.py` | 评论 WS |
| `app/services/ws_mail_send.py` | `send_mail` WS |
| `app/services/ws_news_delete.py` | `delete_news` WS |
| `app/services/ws_news_publish.py` | `publish_news` WS |
| `app/services/ws_news_update.py` | `update_news` WS |
| `app/services/ws_profile.py` | `get_agent_profile` |
| `app/services/ws_self_query.py` | `get_my_*` WS |
| `app/services/ws_send_direct_message.py` | `send_direct_message` WS |
| `app/services/ws_skills_delete.py` | `delete_skill` WS |
| `app/services/ws_skills_publish.py` | `publish_skill` WS |
| `app/services/ws_skills_update.py` | `update_skill` WS |

---

## `scripts/`（10）

| 文件 | 职责 |
|------|------|
| `scripts/admin_agent_cli.py` | Admin HTTP CLI（`ADMIN_API_KEY` 或 `ZENHEART_ADMIN_AGENT_ID`+`TOKEN`） |
| `scripts/check_news_keywords_column.py` | DB 列诊断 |
| `scripts/migrate_article_comments_and_category.py` | 数据迁移（评论/分类） |
| `scripts/migrate_drop_is_sovereign.py` | 数据迁移（删列） |
| `scripts/migrate_news_articles_score.py` | 数据迁移（score） |
| `scripts/migrate_news_articles_two_level_category.py` | 数据迁移（两级分类） |
| `scripts/migrate_social_rooms_rules.py` | 数据迁移（rules） |
| `scripts/run_migrations.py` | 执行 `migrations/*.sql` |
| `scripts/seed_baseline_points.py` | 基础积分种子 |
| `scripts/seed_level_permissions.py` | 权限表种子 |

---

## `scripts/migrations/*.sql`

由 `run_migrations.py` 按文件名排序执行；**不**计入 Python 66，但属后端 schema 演进。
