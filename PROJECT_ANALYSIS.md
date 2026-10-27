# 项目分析报告：AI 内容运营助手（graph_xiaohongshu）

> 分析时间：2026-09-27 ｜ 分析范围：仓库全部源码（后端 33 个 .py、前端 Vue 3 单页应用）

---

## 一、项目定位

这是一个**面向小红书的内容自动化生产服务**。用户输入一个主题方向，系统自动完成：

```
生成爆款选题 → 人工选题 → AI 写长文 → 人工审核 → 提取配图要点 → AI 生成小红书风格配图
```

核心特征有三个：

1. **Human-in-the-loop（人在环中）**：选题和审稿两个环节会真正"暂停"工作流，等人在前端点击后才继续——不是伪中断，是 LangGraph 的 `interrupt()` + `Command(resume=...)` 原生机制。
2. **状态可持久化、可恢复**：工作流状态存进 PostgreSQL，服务重启后线程仍在，支持历史回溯、线程列表、删除。
3. **多用户隔离**：JWT 登录，`thread_id` 用 `{user_id}_{uuid}` 前缀做租户隔离。

---

## 二、整体技术框架

### 2.1 技术栈总览

| 层 | 技术 | 版本要求 | 作用 |
|---|---|---|---|
| Web 框架 | FastAPI | ≥0.128 | 异步 HTTP 接口、自动 OpenAPI 文档 |
| ASGI 服务器 | Uvicorn | ≥0.40 | 运行服务 |
| 工作流编排 | **LangGraph** | ≥1.0.7 | 图状态机、中断/恢复、持久化 |
| LLM 接入 | langchain-openai (`ChatOpenAI`) | ≥1.1.7 | 以 OpenAI 兼容协议调用火山方舟 |
| LLM 模型 | 火山引擎 Doubao（方舟 Ark） | seed-1-8 / seed-1-6-flash | 选题、写作、要点提取 |
| 生图模型 | 火山方舟 Seedream | 接入点 `ep-20260923014947-j8fcl` | 小红书风格配图 |
| 数据库 | PostgreSQL | — | 用户表 + LangGraph checkpoint 表 |
| 异步驱动 | asyncpg（SQLAlchemy）/ psycopg3（Checkpointer） | — | 两套驱动并存，各有分工 |
| ORM | SQLAlchemy AsyncIO | ≥2.0.46 | 仅用于 `users` 表 |
| 状态持久化 | langgraph-checkpoint-postgres (`AsyncPostgresSaver`) | ≥3.0.3 | 图状态快照落库 |
| 配置 | pydantic-settings | ≥2.12 | `.env` → Settings 单例 |
| 认证 | python-jose (JWT) + passlib(argon2/bcrypt) | — | Token 签发与密码哈希 |
| 日志 | structlog + logging | ≥24.1 | 结构化 JSON 日志、按天轮转 |
| 前端 | Vue 3 + Vite + axios | 3.4 / 5.x | 单页操作台 |
| 包管理 | **uv**（`uv.lock` + `pyproject.toml`），`requirements.txt` 为兼容保留 | Python 3.13 | 依赖锁定 |

### 2.2 分层架构

```
┌──────────────────────────────────────────────────────────┐
│  前端 Vue3 (frontend/)  :3000                            │
│  登录注册 · 步骤向导 · SSE 流式渲染 · 线程侧边栏           │
└───────────────────────┬──────────────────────────────────┘
                        │ /api/v1/*  (Vite proxy → :8000)
┌───────────────────────▼──────────────────────────────────┐
│  接口层 app/api/v1/                                       │
│  auth.py(登录注册)  workflow.py(工作流+SSE)  image.py(生图)│
├──────────────────────────────────────────────────────────┤
│  横切层 app/core/ + app/dependencies/                     │
│  config · db · security · middleware · logger · PII 脱敏   │
├──────────────────────────────────────────────────────────┤
│  编排层 app/graph/                                        │
│  state.py(状态定义)  workflow.py(主图+中断)               │
│  subgraphs/topic_selection.py(选题子图)                    │
│  nodes/ planner · writer · visualizer                     │
│  metrics.py(指标)  utils.py(Checkpointer)                 │
├──────────────────────────────────────────────────────────┤
│  服务层 app/services/                                     │
│  llm_service(Doubao 文本)  image_service(Ark 生图)        │
├──────────────────────────────────────────────────────────┤
│  数据层                                                   │
│  PostgreSQL：users 表 + checkpoints/blobs/writes 表       │
│  本地磁盘：static/images/generated/*.png（生成图落盘）     │
└──────────────────────────────────────────────────────────┘
```

### 2.3 工作流拓扑（LangGraph 主图 + 子图）

```
START
  │
  ▼
┌───────────────────────────────┐
│ 子图 topic_selection          │
│  plan_topics ──► human_select_topic ⏸ interrupt
└───────────────┬───────────────┘
                │ (用户选完选题，Command 恢复)
                ▼
          write_draft  ◄──────────────┐
                │                     │
                ▼                     │
          human_review ⏸ interrupt     │
                │                     │
        ┌───────┴────────┐            │
     approve          reject ─────────┘
        │
        ▼
  extract_visuals ──► generate_images ──► END
```

---

## 三、文件职责详解

### 3.1 根目录

| 文件 | 职责 |
|---|---|
| `README.md` | 项目说明。**注意：内容已明显过时**（详见第六节） |
| `pyproject.toml` | uv 工程定义，Python `>=3.13,<3.14`，声明全部生产依赖 |
| `uv.lock` | uv 锁定的完整依赖树（约 172 KB） |
| `requirements.txt` | pip 方式的等价依赖清单，带中文分组注释，兼容老流程 |
| `.env` | **真实运行配置**（含真实 API Key），已被 `.gitignore` 排除 |
| `.env.example` | 配置模板。**⚠️ 内含疑似真实 Key，不应入库** |
| `.gitignore` | 忽略 `.env`、`logs/`、`.venv/`、`node_modules/`、`frontend/dist/` 等 |
| `.python-version` | 固定 Python 版本（3.13） |
| `test_db_connection.py` | 临时调试脚本：用 psycopg 连接池探测 PostgreSQL 连通性。**硬编码了密码**，属遗留文件 |
| `PROJECT_ANALYSIS.md` | 本分析报告 |

### 3.2 应用入口 `app/main.py`

- 启动前把项目根加入 `sys.path`；
- **Windows 关键适配**：`asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())`，因为 psycopg 异步模式不兼容默认的 ProactorEventLoop（必须在建事件循环前设置）；
- `lifespan` 生命周期：启动 → `setup_logging()` → `init_db()`（SQLAlchemy 建表）→ `setup_checkpointer()`（建 LangGraph 表）；关闭 → 关连接池、关 DB；
- 中间件注册顺序：`RequestLoggingMiddleware` → `CORSMiddleware`（Starlette 中后添加的先执行）；
- 挂载 `/static` 静态目录（生成图片的访问入口）；
- 提供 `/`、`/health` 健康检查。

### 3.3 横切层 `app/core/`

| 文件 | 职责 |
|---|---|
| `config.py` | `Settings(BaseSettings)` 读取 `.env`。管理应用名、DB URL、日志 5 项配置、JWT 3 项配置。用 `@lru_cache` 做单例 |
| `db.py` | SQLAlchemy 异步引擎（`pool_size=5, max_overflow=10, pool_pre_ping`）、`async_sessionmaker`、`get_async_session()` 依赖注入生成器（自动 commit/rollback）、`init_db()` / `close_db()` |
| `security.py` | 密码哈希上下文（`argon2` 优先、`bcrypt` 兜底）、`verify_password`、`get_password_hash`、`create_access_token`、`decode_access_token` |
| `middleware.py` | `RequestLoggingMiddleware`：注入 `request_id`（优先取 `X-Request-ID` 头）、记录请求开始/结束/耗时、解析真实客户端 IP（X-Forwarded-For → X-Real-IP → client.host）、回写响应头。另有 `LangSmithTracingMiddleware`（已定义但未启用） |
| `logger.py` | structlog 全套配置：`TimedRotatingFileHandler` 按天轮转保留 30 天、文件恒为 JSON、控制台彩色；自定义 processor 注入 `request_id` / `service`；`AppLogger` 提供语义化方法（`workflow_started`、`draft_approved`、`topic_selected` 等约 20 个业务事件）；导出全局 `app_logger` |
| `pii_anonymizer.py` | 正则驱动的 PII 检测与脱敏。内置 6 类模式：邮箱、信用卡、API Key（含 OpenAI/LangSmith/UUID 格式）、中国手机号、IP、身份证；4 种策略 `redact`/`mask`/`hash`/`block`；`anonymize_dict` 支持递归；导出 `pii_anonymize_processor` 供 structlog 使用 |
| `callbacks.py` | `PIIAnonymizingCallback`（LangChain `BaseCallbackHandler`）：在 `on_llm_start` / `on_chat_model_start` / `on_llm_end` 时对 prompt 与输出做脱敏，保证 LangSmith 追踪里不落敏感信息 |

### 3.4 接口层 `app/api/v1/`

**`auth.py`** — 认证三接口
- `POST /auth/register`：查重 → argon2 哈希 → 建用户
- `POST /auth/login`：校验密码 → 签发 JWT（`sub = user.id`，默认 24h）
- `GET /auth/me`：返回当前用户信息

**`workflow.py`** — 项目最核心的接口文件（约 840 行）
- 8 个 Pydantic 请求/响应模型（含 `NodeMetricInfo` 指标结构）
- 辅助函数 `extract_interrupt_info()`：从 `state_snapshot.tasks[*].interrupts[*].value` 中捞出中断负载——这是 LangGraph 1.0 中断信息的读取方式
- 接口清单：

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/workflow/start` | 启动工作流，跑到选题中断点，返回 5 个选题（非流式 + 结构化输出） |
| GET | `/workflow/state/{thread_id}` | 取状态快照：status、values、next_nodes、is_completed、interrupt_info、node_metrics |
| POST | `/workflow/resume/{thread_id}` | 恢复工作流，`action` ∈ `select_topic`/`approve`/`reject`，内部构造 `Command(resume=...)` |
| GET | `/workflow/history/{thread_id}` | 通过 `aget_state_history` 拉历史快照（最多 20 条） |
| GET | `/workflow/threads` | 线程列表。**直连 psycopg 裸 SQL 查 `checkpoints` 表**，用 `thread_id LIKE '{user_id}_%'` 过滤 |
| DELETE | `/workflow/threads/{thread_id}` | 删除线程，裸 SQL 依次删 `checkpoint_writes` / `checkpoint_blobs` / `checkpoints` |
| POST | `/workflow/stream/resume/{thread_id}` | **SSE 流式**恢复，仅支持 `select_topic` / `reject`（即会生成文章的场景） |

- SSE 实现要点：`stream_graph_updates()` 用 `graph.astream_events(..., version="v2")` 监听 `on_chat_model_start` / `on_chat_model_stream` / `on_chat_model_end`，把 token 逐块推给前端，并从 `usage_metadata` 或 `response_metadata.token_usage` 里抠出 token 统计；事件类型共 7 种：`start`、`resume`、`llm_start`、`llm_token`、`llm_end`、`done`、`error`；响应头带 `X-Accel-Buffering: no` 防 Nginx 缓冲。
- 每个涉及具体线程的接口都先做 `thread_id.startswith(str(current_user.id))` 越权校验。

**`image.py`** — 生图连通性测试接口
- `POST /image/generate`：单张图片生成，默认套用小红书风格提示词模板。

### 3.5 编排层 `app/graph/`

| 文件 | 职责 |
|---|---|
| `state.py` | `AgentState(TypedDict, total=False)`：13 个字段，覆盖选题（topic_direction / generated_topics / selected_topic）、写作（article_content / review_feedback / review_status / revision_count）、视觉（visual_points / image_urls）、元数据（status / error / node_metrics）。另定义 `NodeMetric` 结构与 `INITIAL_STATE` 初始值 |
| `workflow.py` | 主图定义。`human_review_node` 用 `interrupt()` 暂停并返回 `Command(update=..., goto="extract_visuals" | "write_draft")`；`build_workflow_graph()` 注册 5 个节点与 5 条边；`get_compiled_graph()` 编译时挂 checkpointer；`get_graph()` 用全局单例缓存编译结果 |
| `subgraphs/topic_selection.py` | 选题子图：`plan_topics` → `human_select_topic`（`interrupt()` 等人选，返回 `Command(goto=END)` 交还主图）。子图编译时**不带 checkpointer**，由主图统一管理状态 |
| `nodes/planner.py` | `plan_topics_node`：调 `llm_service.plan_topics()` 结构化输出，取 `topic.title` 列表，写 `status="topics_generated"` |
| `nodes/writer.py` | `write_draft_node`：有 feedback 时 `revision_count += 1`，调 `stream_write_draft_with_usage()`（流式收集完整内容），写 `status="draft_generated"` |
| `nodes/visualizer.py` | `extract_visuals_node`（提取 3 个配图要点）+ `generate_images_node`（并行生图）。**生图失败不阻塞流程**：部分/全部失败也置 `status="completed"`，只把失败信息写进 `error` |
| `metrics.py` | `NodeMetricsTracker` + `MetricsContext` 上下文管理器（`with` 块自动计时）+ `LLMUsage` + `merge_metrics()` 追加指标 |
| `utils.py` | Checkpointer 生命周期：`setup_checkpointer()` 先用 autocommit 连接执行 `setup()`（因为 `CREATE INDEX CONCURRENTLY` 不能跑在事务块里），再建 `AsyncConnectionPool(min=1, max=10)` 交给 `AsyncPostgresSaver`；`get_checkpointer()` / `close_checkpointer()` |

> 说明：`nodes/__init__.py` 明确注明 `human_select_topic_node` 与 `human_review_node` 已迁到 `workflow.py` 和子图中，`nodes/` 只保留三个纯 AI 节点。

### 3.6 服务层 `app/services/`

**`llm_service.py`**（约 330 行，文本侧全部能力）
- 三个懒加载的 `ChatOpenAI` 实例，构成**双模型三温度策略**：

| 实例 | 模型 | 温度 | 用途 |
|---|---|---|---|
| `llm` | `doubao-seed-1-8-251228` | 0.7 | 文章写作（质量优先） |
| `llm_fast` | `doubao-seed-1-6-flash-250828` | 0.7 | 选题生成（速度优先） |
| `llm_extract` | `doubao-seed-1-6-flash-250828` | 0.4 | 配图要点提取（要稳定） |

- 三套 System Prompt：`TOPIC_SYSTEM_PROMPT`（小红书爆款标题公式：数字+痛点/悬念反转/情绪共鸣/身份代入/对比冲击，15 字内）、`ARTICLE_SYSTEM_PROMPT`（800-1200 字、口语化、emoji、结尾引导评论）、`VISUAL_SYSTEM_PROMPT`（3 条纯视觉描述、封面优先、禁止文字与敏感内容）
- 方法：`plan_topics`（`with_structured_output(TopicsResponse, include_raw=True)`，失败自动降级到 `_plan_topics_fallback` 手动剥 JSON）、`write_draft`（非流式）、`stream_write_draft_with_usage`（流式 + token 统计 + 无 usage 时按字符数估算）、`extract_visual_points`（截断 1500 字、清洗编号前缀、最多取 3 条）
- 统一挂载 PII 脱敏 callback

**`image_service.py`**
- `AsyncArk` 客户端调 `images.generate`（`sequential_image_generation="disabled"`、`response_format="url"`、`size=2K`、`watermark=True`）；
- 因为返回 URL 有时效，**立即用 httpx 下载并落盘**到 `static/images/generated/xhs_{时间戳}_{8位uuid}.png`，返回静态访问路径；
- 失败重试一次：换随机 `FALLBACK_PROMPTS`；批量时 `asyncio.gather` 并行；
- API Key 优先 `ARK_API_KEY`，缺省回退 `LLM_API_KEY`；**无 Key 时构造即抛错**（模块级单例，会影响启动）。

**`__init__.py`** — 导出单例与 `get_llm_service()` / `get_image_service()` 工厂函数。

### 3.7 其他后端目录

| 文件 | 职责 |
|---|---|
| `app/models/user.py` | `User` 模型：UUID 主键、唯一索引 `username`、`password_hash`、创建/更新时间 |
| `app/dependencies/auth.py` | `HTTPBearer` 方案；`get_current_user()`（解码 JWT → 查库 → 返回 User，失败 401）；`get_current_user_optional()`（允许匿名） |
| `app/api/v1/__init__.py`、各 `__init__.py` | 包初始化，`nodes/__init__.py` 做节点统一导出 |

### 3.8 前端 `frontend/`

| 文件 | 职责 |
|---|---|
| `package.json` | Vue 3.4 + vue-router 4 + axios 1.6；脚本 `dev`/`build`/`preview` |
| `vite.config.js` | dev 端口 3000，把 `/api` 和 `/static` 代理到 `http://localhost:8000` |
| `index.html` | 单页挂载点 |
| `src/main.js` | 5 行，`createApp(App).mount('#app')`（**vue-router 已安装但未使用**） |
| `src/api.js`（346 行） | axios 实例（baseURL `/api/v1`、120s 超时）；Token 存 localStorage；请求拦截器自动加 `Bearer`；响应拦截器 401 时清 Token 并派发 `auth:logout` 事件；封装全部 REST 接口；**SSE 用原生 `fetch` + `ReadableStream` 手写解析**（`handleSSEStream` 按 `data: ` 分行 JSON 解析，映射 7 种事件到回调） |
| `src/App.vue`（1216 行） | 整个界面。登录/注册、线程侧边栏（列表/切换/删除）、4 步向导（选题→写作→审核→配图）、SSE 流式文章逐字渲染、流式事件日志面板、节点耗时与 token 统计卡片 |
| `src/style.css` | 全局样式 |
| `dist/` | 构建产物（已 gitignore） |

### 3.9 资源与脚本

| 路径 | 说明 |
|---|---|
| `scripts/init_db.sql` | 建库建表参考脚本。建 `users` 表 + `uuid-ossp` 扩展；checkpoint 相关表由 `AsyncPostgresSaver.setup()` 自动创建 |
| `static/images/generated/` | 生成图片落盘目录（现有 10 张测试图，命名含 2026-02 与 2026-09 两批） |
| `logs/app.log` | 当前结构化 JSON 日志，已约 **6.4 MB**；`app.log.2026-09-26` 为轮转历史 |

---

## 四、核心机制深挖

### 4.1 中断与恢复（Human-in-the-loop）

这是整个项目最值得理解的部分：

1. **暂停**：节点内调用 `interrupt(payload)`，payload 会存进 checkpoint 的 `tasks[*].interrupts[*].value`，接口层用 `extract_interrupt_info()` 读出来返回给前端。
2. **前端展示**：`interrupt_info.action_required` 为 `select_topic` 或 `review`，前端据此渲染选题卡片或审稿面板。
3. **恢复**：`graph.ainvoke(Command(resume={...}), config)`，`interrupt()` 的返回值即为这里的 `resume` 内容。
4. **分支**：审稿节点根据 `action` 返回 `Command(goto=...)` 决定去 `extract_visuals` 还是回 `write_draft`——驳回重写靠的是 `goto="write_draft"` 形成环，`revision_count` 递增。

> 注意：LangGraph 1.0 不再需要 `interrupt_before` 参数，中断完全由 `interrupt()` 函数控制。

### 4.2 双驱动 + 双 ORM 的数据库访问

项目里 PostgreSQL 被两条路径访问，职责清晰但容易混淆：

| 路径 | 驱动 | 用途 |
|---|---|---|
| SQLAlchemy AsyncIO | asyncpg | `users` 表 CRUD、`init_db()` 建表 |
| 裸 psycopg3 / AsyncConnectionPool | psycopg | LangGraph Checkpointer、线程列表/删除的裸 SQL |

### 4.3 指标与可观测性

三层可观测性：

- **业务指标**：`node_metrics` 随状态流转，每个节点追加 `{node_name, duration_ms, start/end_time, input/output/total_tokens, model}`，前端汇总展示总耗时与总 token。
- **结构化日志**：structlog JSON + `request_id` 贯穿请求全链路，日志同时做 PII 脱敏。
- **LLM 追踪**：`.env` 里已配置 LangSmith（`LANGCHAIN_TRACING_V2=true`），配合 PII callback 保证追踪数据不泄敏。

### 4.4 多租户隔离

- `thread_id = f"{current_user.id}_{uuid4()}"`
- 所有线程级接口校验 `startswith(user.id)`
- 线程列表用 `LIKE '{user_id}_%'` 过滤

---

## 五、关键调用链路

```
① 选题（非流式）
POST /workflow/start
  └─ graph.ainvoke(INITIAL_STATE + topic_direction)
       └─ 子图 plan_topics → llm_fast.with_structured_output
       └─ human_select_topic → interrupt() ⏸
  └─ 返回 {thread_id, generated_topics[5], interrupt_info}

② 选完选题写文章（SSE 流式）
POST /workflow/stream/resume/{thread_id}  {action: select_topic}
  └─ Command(resume={selected_topic}) → ainvoke
       └─ write_draft → llm.astream  ← token 逐块经 SSE 推给前端
       └─ human_review → interrupt() ⏸
  └─ SSE: llm_token × N → llm_end(usage) → done

③ 审核
通过: POST /workflow/resume {action: approve} → extract_visuals → generate_images → END
驳回: POST /workflow/stream/resume {action: reject, feedback} → write_draft（重写，回到 ②）
```

---

## 六、发现的问题与改进建议

### 高优先级

1. **密钥外泄风险**：`.env.example` 中 `LLM_API_KEY`、`LANGCHAIN_API_KEY` 是疑似真实凭据；`test_db_connection.py` 硬编码数据库密码 `123456`。建议：把示例文件改为占位符，并从版本历史中彻底清除（若已推送过）。
2. **CORS 配置矛盾**：`allow_origins=["*"]` 与 `allow_credentials=True` 同时开启会被浏览器拒绝（规范禁止通配符 + 凭据）。建议改为显式域名白名单。
3. **JWT 默认密钥**：`jwt_secret_key` 默认值写死在代码里，生产环境必须通过环境变量覆盖。

### 中优先级

4. **README 严重过时**，与代码不符之处：
   - 项目结构写 `backend/`，实际是仓库根目录；
   - 列了 `nodes/human.py`，该文件**不存在**（人工节点已迁至 `workflow.py` / 子图）；
   - 建库命令写 `CREATE DATABASE aicontent`，实际 `.env` 用的是 `langgraph_db`；
   - 说"生成 3-5 个选题"，实际固定 5 个；
   - 未提及新增的认证、SSE 流式、指标统计、日志系统。
5. **裸 SQL 耦合内部表结构**：`/threads` 和 `DELETE /threads/{id}` 直接操作 `checkpoints`/`checkpoint_writes`/`checkpoint_blobs`。LangGraph 升级若改表结构会直接崩。建议改用官方 API 或抽象成一层仓储。
6. **服务单例在 import 期构造**：`llm_service` / `image_service` 在模块导入时实例化，`image_service` 缺 Key 直接抛错，会导致应用无法启动。建议改为懒加载 + 启动时显式校验并给出可读报错。
7. **删除线程未做软删除/二次确认**，且 `DELETE` 只删了 3 张表，未考虑 `checkpoint_migrations` 之外的关联数据。
8. **前端单文件 1216 行**：`App.vue` 承担了登录、向导、日志、指标全部职责，`vue-router` 装了没用。建议按视图/组件拆分。

### 低优先级

9. `logs/app.log` 已 6.4 MB 且仍在增长（虽然按天轮转保留 30 天，但单日无大小上限）；`static/images/generated/` 无限增长，无清理策略。
10. `LangSmithTracingMiddleware` 定义了但没注册，属死代码。
11. token 估算逻辑（`len(text) // 2`）仅在中文字符下勉强合理，混排英文会明显偏差。
12. 缺少测试：仓库无 `tests/`，无 CI 配置。
13. `pyproject.toml` 的 `description` 还是模板默认值 `"Add your description here"`。

---

## 七、总结

**技术选型的合理性**：用 LangGraph 做编排是恰当的选择——这个业务的本质就是"有环、需人工介入、状态要能持久化"的流程，传统 CRUD 或简单链式调用很难优雅实现"驳回重写"和"暂停数小时后再恢复"。`AsyncPostgresSaver` 让"暂停"跨进程、跨重启有效，这是整个设计的地基。

**代码质量**：分层清晰（api / core / graph / services / models 边界明确），配置与密钥走环境变量，日志与脱敏做得比多数同类项目认真，指标统计贯穿每个节点。

**主要短板**：文档与代码脱节、密钥管理不严、对 LangGraph 内部表的裸 SQL 耦合、前端未拆分、零测试覆盖。
