# Architecture

Rubbish 的架构契约文档。每个模块都要遵守,偏离即 bug。

## 一句话概括

Rubbish 是一个**模块化、多租户的学术期刊发表平台**:核心只持有身份、租户、角色、模块注册表;每个领域能力(投稿、审稿、阅读、订阅、推荐...)都作为独立模块在启动时挂载到核心。

## 两层模型

```
┌─────────────────────────────────────────────────────────────┐
│                    前端 SPA  (apps/frontend)                  │
│   核心外壳  +  各启用模块贡献的 UI 路由 chunk                    │
└──────────────────────────┬──────────────────────────────────┘
                           │  HTTP / SSE / WebSocket
┌──────────────────────────┴──────────────────────────────────┐
│                    后端 API  (apps/backend)                  │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  core:  租户 · 身份 · 角色 · 模块注册表 · admin · 部署    │ │
│  └───────────────────────┬─────────────────────────────────┘ │
│                          │ 启动时按依赖顺序加载                  │
│  ┌──────────┬────────────┴───────────┬──────────┬───────────┐ │
│  │ catalog  │ submission │ review  │ reader   │ export    │ │
│  ├──────────┼────────────┼─────────┼──────────┼───────────┤ │
│  │ follows  │ library    │ ingest  │recomm.   │notif.     │ │
│  ├──────────┼────────────┼─────────┼──────────┼───────────┤ │
│  │gamificat.│announcem.  │ quality │          │           │ │
│  └──────────┴────────────┴─────────┴──────────┴───────────┘ │
└──────────────────────────┬──────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   PostgreSQL 17      Redis (规划中)     object storage (规划中)
   (主库 + RLS)       (缓存 + 限流)       (PDF、上传文件)
```

## 核心层(core)负责什么

核心层刻意保持最小,只承担每个学术期刊站点都需要的"地基":

1. **租户** — 每个领域表都带 `tenant_id`。单租户部署只有一行 + `RUBBISH_TENANCY_MODE=single`;多租户部署通过 host-header 解析租户并按 `tenant_id` 隔离数据。**单租户模式已实现**,多租户模式(host-header → tenant 查找表)尚未实现(`TenantContextMiddleware._resolve_tenant` 默认返回 `None` 即 default-deny)。

2. **身份与访问** — 本地用户账号(已实现)、按租户隔离的角色 + 权限模型(已实现)、短时 access token + httpOnly cookie refresh(已实现)。邮件验证 + 密码重置(无状态签名 token 绑定 `token_version`,已实现)。OIDC SSO via authlib(Google / GitHub / Generic / Keycloak,已实现,通过环境变量配置)。邮件发送走可插拔 sender(console dev / SMTP relay for Mailgun / SendGrid / SES / Postmark,已实现)。

3. **模块注册表** — 后端启动时按依赖顺序加载 `app/modules/<name>/` 下的每个模块,每个模块声明自己的名字、依赖、模型、路由、admin hooks。核心按拓扑序挂载并运行各自的迁移,前端通过 `/api/modules` 端点知道渲染哪些 UI。

4. **admin shell** — `app.api.admin` 提供按租户隔离的 admin REST API:用户列表 + 启用/停用、审计日志。React SPA 在 `/admin` 下展示。角色/权限编辑、模块启停尚未实现。

5. **部署** — Docker Compose(dev + prod)、Caddy TLS、Alembic 迁移在容器启动时执行、structlog JSON 日志、health 端点上报模块加载状态。详见 [docs/integrations.md](integrations.md) 的 SMTP + OIDC + Crossref/arXiv 接入。


## 1.0.0 新增模块（等级 / 公告 / 评分）

- **gamification** — 九级双轨阶梯（`ladder.py`，代码即口径）、XP 台账
  （`user_xp_events`，唯一约束保证幂等）、成就定义（`badges.py`，27 枚）与
  渐进展示。级别门禁通过 `app/api/levels.py` 的 `require_level(n)` 注入到
  评论（L2）、阅读列表（L2）、投稿（L3）三条写路径；`require_rules_ack`
  与 `users.rules_ack_version` 绑定，规范改版后旧确认自动失效。
- **announcements** — 单表 + 发布窗口；公开只读 `/api/announcements/active`，
  管理员 CRUD 带审计。首访卡由前端 localStorage 记忆，不落用户维度状态。
- **quality** — RQS v1.0 评分口径（`rubric.py`）：四类稿件画像各自一套维度
  权重（合计 100），等级带 A+/A/B/C/D，纯度系数 = RQS/50。评分由离线流水线
  写入 `resources.quality_*`，运行时只读；口径公开在 `/api/quality/rubric`，
  改口径必须升 `RUBRIC_VERSION` 并整库重评。

这三者都遵循同一约束：**口径进代码、结果进数据**。数据库只存分数与明细，
不存可编辑的权重表，避免两篇不同月份入库的文章不可比较。

## 1.8.0 变更：投稿零门槛 + 投稿驱动升级（scoring 2.0）

- **投稿门槛放开**：`POST /api/submissions` 移除 `require_level(3)`——注册登录即可投，
  唯一前置是确认当版《投稿规范》（`rules_ack_version`，合规动作而非等级门槛）。
- **升级口径 2.0**（ladder.py `SCORING_VERSION = "2.0"`）：XP 单独只能买到 L3
  （`XP_ONLY_MAX_LEVEL = 3`）；L4 = XP≥400 **且** 录用稿件 ≥1——积分满不再是
  充分条件，投稿并录用才是升级的重磅。L5/L6 申请制、L7+ 提拔制不变。
- **实现**：`effective_level(xp, roles, is_admin, accepted_papers)` 增加必传录用数
  （类型签名强制全部调用点同步口径）；录用数查询抽为
  `gamification/applications.py::accepted_paper_count`（L4 指标与 L5 画像共用）；
  `level_snapshot` 转 async 并返回 `metric_remaining`（下一级还差几篇录用）。
- **口径变更遵守 ladder 自身约束**：改口径必须升 SCORING_VERSION 并同步前端展示。

## 1.7.0 新增：职员角色申请（L5/L6）

等级阶梯里 L5 审稿人、L6 资深审稿人原先只能由管理员在 `/admin/users` 直接授角色，
用户侧没有「我该怎么升」的可执行路径。1.7.0 补上申请制：

- **资格口径仍进代码** — `gamification/applications.py` 冻结两条门槛：L5 = 至少
  1 篇稿件被录用且最高 RQS ≥ 60（C 级下限，未评分稿件不参与）；L6 = 已是 L5 且
  完成审稿 ≥ 5 份。L7–L9 编辑职不开放申请，只由编辑部提拔。
- **申请进数据** — `role_applications` 表（迁移 012）承载 `pending → approved|rejected`
  状态机，终态不可回滚（重申 = 新行）。`tenant_id` + RLS 与其余模块一致；
  `uq_role_applications_pending` 部分唯一索引保证「同一用户同一角色仅一条待审」，
  审批端点对申请行 `with_for_update()` 防止并发重复批准。
- **审批即授权** — `POST /api/gamification/admin/applications/{id}/decision` 在同一
  事务内授 `UserRole`、写站内通知、写审计；拒绝原因随通知下发。
- **顺带的资料补齐** — `users.bio`（≤200 字，空串即清除）在同一迁移落地，
  设置页可编辑、个人中心展示。

## 模块长什么样

模块是 `app/modules/<name>/` 下一个自包含的包,固定形态:

```
app/modules/<name>/
├── __init__.py            # 通过 ModuleManifest 注册到核心
├── models.py             # SQLAlchemy 模型,全部带 tenant_id
├── schemas.py            # Pydantic 请求/响应类型
├── routes.py             # FastAPI router,挂载在 /api/<name>
├── services.py           # 业务逻辑(跨模块复用时才写)
└── (tests 在 apps/backend/tests/test_<name>.py)
```

模块之间**默认不互相 import**;若需跨模块调用,必须在 `ModuleManifest.dependencies` 中声明。核心在启动时检查依赖图,有环或缺依赖会拒绝启动。

## 租户隔离与迁移

- 每个领域表都有非空 `tenant_id` 列,带索引。
- **双层隔离防御**:
  - **Layer 1 应用层**:每个 SELECT/UPDATE/DELETE 都显式追加 `Model.tenant_id == require_tenant_id()`(或 `current_user.tenant_id`)。漏写过滤是 bug。
  - **Layer 2 数据库层**:PostgreSQL RLS。`app.core.db.get_db` 在每个事务 BEGIN 时 `SET LOCAL app.current_tenant_id = :tid`(通过 `after_begin` 事件监听器),即使应用层漏写过滤,数据库也会拒掉跨租户行。SQLite 测试环境跳过 RLS(SQLite 没有 RLS),所以应用层过滤是强制的,由 `tests/test_rls_isolation.py` 在 PostgreSQL 17 上验证。
- 迁移文件在 `apps/backend/alembic/versions/`,每个模块一份,编号 `NNN_<module>_module.py`。共享的 `target_metadata = Base.metadata`(见 `alembic/env.py`)会自动检测新模块表,因为每个模块都从 `app.models` 导入 `Base`。
- 单租户模式 = 多租户模式里只有一行;没有独立代码路径,没有 `if single_tenant` 分支。

## 前端组合

`apps/frontend/` 下是一个单 SPA。技术栈:React 19 + TypeScript + Vite 7 + Tailwind CSS v4 + TanStack Router v1(file-based + autoCodeSplitting)+ TanStack Query v5 + Zustand(auth store)+ shadcn/ui。

覆盖全部 10 个领域模块:catalog 列表/详情/创建、reader(PDF 嵌入 + 进度 + 历史)、submissions(作者 + admin 审稿)、ingest(BibTeX/RIS/CSV 解析 + Crossref/arXiv 抓取)、library(阅读列表 CRUD + 增删条目)、notifications、recommendations、admin(用户 + 审计日志)。Auth 流程覆盖登录/注册/登出、邮件验证、密码重置、OIDC SSO 回调。一个镜像同时打包后端 + 前端,版本不会漂移。

## 我们选择不做的事

- **不做插件市场**:模块在本仓库内 vendored。第三方模块通过 fork 仓库安装,我们不跑 registry。
- **不做 per-module 数据库**:所有模块共享租户的 PostgreSQL,跨模块 join 仍然可行。
- **不做 per-module 独立前端**:一个 SPA、一个 bundle、一次部署。模块 UI 是路由 chunk,不是独立 app。
- **不做事件总线**:跨模块通信走显式 service 方法,不走 pub/sub 层。submission 模块要通知 follows 模块,直接调用 service,不发消息。

## 参考

- [README.md](../README.md) — 项目概览与路线图
- [docs/integrations.md](integrations.md) — SMTP 邮件 + OIDC SSO + Crossref/arXiv 接入指南
