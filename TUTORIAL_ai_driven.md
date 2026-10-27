# 全 AI 驱动开发教程：小红书内容自动化助手（graph_xiaohongshu）

> 定位：这是一份「人只出想法、AI 写全部代码」的复现手册。
> 适用对象：想照着这个项目从 0 做一遍的人。
> 说明：文中提示词是根据仓库当前代码**反推重建的可复现版**（原始对话记录未留存），每一条都在当前代码base 上有对应产物，可直接使用。

---

## 0. 先讲方法论：全 AI 开发的三件事

人的工作量被压缩到三件事：

1. **提需求**：用大白话讲清楚"要什么"（第 1 阶段）。
2. **点按钮 / 开通服务**：注册账号、拿 Key、装数据库（第 2 阶段，AI 只能给清单，动手必须人来做）。
3. **贴报错**：跑不通就把终端报错原样粘回给 AI，不做二次加工。

其余全部交给 AI：技术选型、目录结构、代码、Prompt 工程、联调、修 bug、写文档。

**关键心法（决定成败的三条）**

| 心法 | 做法 | 不做会怎样 |
|---|---|---|
| 先立"项目宪法" | 第 3 阶段生成一份规则文件，之后**每轮对话都带上** | AI 每轮风格漂移，代码互相打架 |
| 一次只做一件事 | 一个提示词只完成一个模块，做完就验证 | 一次生成 20 个文件，出错无法定位 |
| 让 AI 自己产出验证方式 | 每个提示词结尾都要求"告诉我怎么验证" | 你不知道它到底做没做完 |

---

## 1. 阶段总览

| # | 阶段 | 人做什么 | AI 做什么 | 当前产出（已在仓库中） |
|---|---|---|---|---|
| 0 | 需求澄清与产品定义 | 说一句话需求 | 展开成 PRD + 流程图 + 术语表 | 理念沉淀在本文件 |
| 1 | 技术选型与架构设计 | 拍板 | 出方案对比 + 分层架构 + 数据模型 | `PROJECT_ANALYSIS.md` 第二、三节 |
| 2 | 开通外部服务 | 注册、拿 Key、装 PG | 出开通清单 + 连通性验证脚本 | `.env` / `.env.example` / `test_db_connection.py` |
| 3 | 项目骨架与配置 | 装 uv / Node | 建目录、`pyproject.toml`、`config.py`、`main.py` | `pyproject.toml` / `app/core/*` / `app/main.py` |
| 4 | LLM 服务层与 Prompt 工程 | 无 | `LLMService` + 三套 System Prompt + 结构化输出兜底 | `app/services/llm_service.py` |
| 5 | LangGraph 编排层（核心） | 无 | State、3 个 AI 节点、中断/恢复、子图、指标 | `app/graph/**` |
| 6 | 持久化与多用户 | 无 | Checkpointer、users 表、JWT、线程隔离 | `app/graph/utils.py` / `app/api/v1/auth.py` |
| 7 | HTTP 接口层（含 SSE 流式） | 无 | 8 个接口、中断负载解析、SSE 事件流 | `app/api/v1/workflow.py` |
| 8 | 配图生成服务 | 在方舟开通生图接入点 | Ark SDK 调用、下载落盘、失败重试 | `app/services/image_service.py` |
| 9 | 前端操作台 | 无 | Vue3 单页、步骤向导、SSE 逐字渲染 | `frontend/src/App.vue` / `api.js` |
| 10 | 可观测性加固 | 无 | structlog、PII 脱敏、节点指标、LangSmith | `app/core/logger.py` / `pii_anonymizer.py` / `graph/metrics.py` |
| 11 | 联调验收与收尾 | 跑一遍完整流程 | 修 bug、补文档 | 10 张已生成配图、`logs/app.log` |

---

## 2. 阶段 0：需求澄清与产品定义

### 你的原始输入（人只需要说这么多）

> "我想做一个自动写小红书的工具：我给它一个方向，它自己出选题，我挑一个，它写文章，我审核，通过后它配图。中间我要能插手。"

### 给 AI 的提示词

```text
# 角色
你是产品经理 + 系统架构师。

# 我的原始需求（大白话，不要嘲笑）
"我想做一个自动写小红书的工具：我给它一个方向，它自己出选题，我挑一个，
它写文章，我审核，通过后它配图。中间我要能插手。"

# 你要输出（用中文，Markdown）
1. 一句话价值主张
2. 用户故事 5 条（作为…我想要…以便…）
3. 主流程：用 Mermaid flowchart 画出完整流程，必须包含两个"人工停下来做决定"的节点，
   以及"审核驳回后回到写作"的回环
4. 明确列出：哪些环节是 AI 做、哪些是人做、哪些是外部服务做
5. 边界与非目标：这个 v1 明确不做什么（比如不做定时发布、不做多平台适配）
6. 关键术语表：选题 / 草稿 / 审核 / 配图要点 / 线程(thread) —— 每个给一句话定义，
   后续代码里的字段名要跟这里对齐

# 要求
- 不要写代码
- 不要推荐具体框架（下一阶段再做）
- 有歧义的地方，用"待确认"列出，不要自己替我拍板
```

### 验收
- 流程图里能清楚看到 2 个「暂停」点和 1 个「回环」。
- 术语表里的词，后面会出现在 `AgentState` 的字段名里。

---

## 3. 阶段 1：技术选型与架构设计

### 给 AI 的提示词

```text
# 任务：为上一阶段的需求做技术选型与架构设计

# 我的硬约束
- 我全程用 AI 写代码，所以我需要"生态成熟、文档多、AI 熟悉"的技术，不要小众框架
- 后端 Python，前端要一个能跑起来的操作界面（不要命令行）
- 工作流必须支持：中途暂停等人工、暂停几小时后还能恢复、驳回后回到上一步重写
- 数据库用 PostgreSQL（本地已有）

# 你要输出
1. 技术选型表：每一层给 2-3 个候选 + 推荐 + 推荐理由（重点回答：为什么工作流编排
   不能用普通的 async 函数链/Celery，为什么需要图状态机）
2. 分层架构图（ASCII 或 Mermaid）：前端 / 接口层 / 编排层 / 服务层 / 数据层，
   每层标注目录名和职责
3. 数据模型设计：
   - 工作流状态（State）有哪些字段，每个字段的类型和含义
   - 需要持久化的表有哪些（注意：用户表我们自己建，工作流状态表由框架自动建）
4. API 清单：路径 / 方法 / 作用，至少覆盖 启动、查状态、恢复（三种动作）、查历史、列线程、删线程
5. 风险清单：你认为这个方案里最容易出问题的 5 个点

# 要求
选型要写具体版本号下限，不要写"最新版"。
```

### 本项目的最终选型（AI 给出、你拍板后锁死）

| 层 | 选型 | 关键理由 |
|---|---|---|
| 编排 | **LangGraph ≥1.0.7** | 原生支持 `interrupt()` 暂停、`Command(resume=)` 恢复、`goto` 形成回环、Checkpointer 持久化——这四点正好是需求的全部难点 |
| Web | FastAPI ≥0.128 + Uvicorn | 异步、自带 OpenAPI 文档，SSE 好写 |
| LLM | 火山方舟 Doubao，用 **langchain-openai 的 ChatOpenAI** 走 OpenAI 兼容协议 | 不用学新 SDK，LangChain 生态直接复用 |
| 生图 | 火山方舟 Seedream（AsyncArk SDK） | 与 LLM 同账号，Key 可复用 |
| 持久化 | PostgreSQL + `AsyncPostgresSaver` | 服务重启后线程还在，暂停可跨进程 |
| ORM | SQLAlchemy AsyncIO（仅 users 表） | 业务表自己管，状态表交给框架 |
| 前端 | Vue 3 + Vite（不用构建路由） | 单文件即可，AI 一次能写对 |
| 环境 | **uv** + Python 3.13 | 锁文件可复现 |

---

## 4. 阶段 2：开通外部服务（这一步必须人来点）

AI 干不了的事：注册账号、实名、拿密钥。让 AI 给你清单和验证脚本。

### 给 AI 的提示词

```text
# 任务：给我一份"外部服务开通清单 + 连通性验证脚本"

# 已定选型
火山方舟(LLM+生图) / LangSmith(追踪) / 本地 PostgreSQL / uv / Node

# 输出两部分

## 第一部分：开通清单（给人看的步骤）
每一项都写清楚：
- 去哪个网址、点哪几步
- 最终要拿到什么（Key？接入点ID？连接串？）
- 拿到后填到 .env 的哪个变量
- 免费的额度/限制提示

## 第二部分：验证脚本
写一个 Python 脚本 test_db_connection.py，用 psycopg 测 PostgreSQL 连通性，
打印：是否连通、当前库名、当前用户、server version。
要求：读 .env 里的 POSTGRES_URI，失败时打印常见原因对照表
（服务没起 / 端口不对 / 密码错 / 库不存在 / pg_hba 拒绝）。
```

### 开通清单（实际项目用的）

#### 4.1 火山引擎方舟（LLM）

1. 注册火山引擎账号 → 完成实名认证。
2. 进入**方舟控制台** → 「模型推理」→ 开通模型：
   - `doubao-seed-1-8-251228`（写作，质量优先）
   - `doubao-seed-1-6-flash-250828`（选题 + 要点提取，快且便宜）
3. 「推理接入点」→ **创建接入点**，绑定上面某个模型 → 得到形如 `ep-xxxxxxxxxx-xxxxx` 的 ID。
4. 「API Key 管理」→ 新建 Key → 这就是 `LLM_API_KEY`。
5. OpenAI 兼容地址固定为：`https://ark.cn-beijing.volces.com/api/v3`
   → 这就是 `LLM_BASE_URL`。

> 关键点：方舟兼容 OpenAI 协议，所以代码里可以直接用 `ChatOpenAI(model=..., base_url=..., api_key=...)`，`model` 既可以是模型名也可以是接入点 ID。

#### 4.2 火山引擎方舟（生图）

1. 方舟控制台 → 「图像生成」→ 开通 Seedream 系列模型。
2. 创建**生图接入点** → 本项目实际用的是 `ep-20260923014947-j8fcl` → 即 `IMAGE_MODEL`。
3. 生图要用官方 SDK `volcenginesdkarkruntime`（`AsyncArk`），与文本侧不是同一个调用方式。
4. `ARK_API_KEY` 可留空，代码里会自动回退到 `LLM_API_KEY`。

#### 4.3 LangSmith（LLM 追踪，可选但强烈建议）

1. 打开 smith.langchain.com → 用 GitHub/Google 登录 → 创建 API Key → `LANGCHAIN_API_KEY`。
2. `.env` 里设 `LANGCHAIN_TRACING_V2=true`、`LANGCHAIN_PROJECT=xiaohongshu-content-assistant`。
3. 有了它，每次 LLM 调用（提示词、返回、token）都能在网页上回放——**调 Prompt 阶段省一半时间**。

#### 4.4 本地 PostgreSQL

```sql
-- psql -U postgres
CREATE DATABASE langgraph_db;
-- 库名是 langgraph_db（注意：README 里写的 aicontent 是错的，已过时）
```

需要**两条**连接串（两个驱动各用一条，后面阶段会解释为什么）：

```env
DATABASE_URL=postgresql+asyncpg://postgres:你的密码@localhost:5432/langgraph_db   # SQLAlchemy 用
POSTGRES_URI=postgresql://postgres:你的密码@localhost:5432/langgraph_db           # LangGraph Checkpointer 用
```

#### 4.5 运行时

- Python 3.13 + **uv**（`uv sync` / `uv run`，不要 pip 全局装）
- Node 22（`frontend/` 下 `npm i && npm run dev`）

### 验收
`python test_db_connection.py` 打印连通 + 库名正确。

---

## 5. 阶段 3：项目骨架、"项目宪法"与配置层

### 5.1 先让 AI 生成"项目宪法"（最重要的一步）

```text
# 任务：为本项目生成一份"项目宪法"，存为 PROJECT_RULES.md

我会把它作为之后每一次对话的固定前缀，所以你要写得像给我（和未来的你）的硬约束。

内容必须包含：
1. 项目根目录与目录职责（后端就在这一个目录，不要再套一层 backend/）
2. 锁死的技术栈与版本下限
3. 代码风格：中文注释 / 中文 docstring / 类型标注 / 全异步
4. 依赖管理：用 uv（uv add / uv run），禁止 pip install 到全局
5. 安全红线：所有密钥走 .env，禁止硬编码；日志里禁止出现密钥、手机号、邮箱
6. 协作规则：改代码前先读相关文件；一次只做一件事；不要删已有功能；
   完成后必须列出"改了哪些文件 + 怎么验证"
7. 目录结构树（空的骨架，后续按这个长）
```

> 之后每一次对话，开头都粘上："遵守 PROJECT_RULES.md，下面是本次任务：……"

### 5.2 骨架与配置

```text
# 任务：搭建 FastAPI 项目骨架与配置层
遵守 PROJECT_RULES.md。

# 要创建
- pyproject.toml（uv 工程，python = ">=3.13,<3.14"，依赖：fastapi / uvicorn[standard] /
  langgraph / langgraph-checkpoint-postgres / langchain-openai / sqlalchemy[asyncio] /
  asyncpg / psycopg[binary,pool] / psycopg-pool / pydantic-settings / python-dotenv /
  python-jose[cryptography] / passlib[bcrypt] / argon2-cffi / structlog / httpx /
  volcengine-python-sdk[ark]）
- .env.example（每项中文注释，值用占位符，不要写真 Key）
- app/core/config.py：Settings(BaseSettings)，从 .env 读，@lru_cache 单例。
  至少含：app_name / debug / database_url / postgres_uri / LLM 相关 5 项 /
  JWT 3 项 / 日志 5 项 / 生图 4 项
- app/core/db.py：SQLAlchemy 异步引擎（pool_size=5, max_overflow=10, pool_pre_ping）、
  async_sessionmaker、get_async_session 依赖（自动 commit/rollback）、init_db / close_db
- app/main.py：FastAPI 实例 + lifespan（启动建表、关闭释放）+ CORS +
  挂载 /static + / 和 /health

# 硬约束
- Windows 兼容：因为 psycopg 异步模式不兼容默认的 ProactorEventLoop，
  必须在创建任何事件循环**之前**设置
  asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())，
  并且这行要在 import 顺序上早于 uvicorn 启动
- 启动日志用中文，并提示 /docs 地址

# 完成后告诉我如何在 8000 端口启动并访问 /docs
```

### 本阶段踩坑（已固化在代码里）

1. **Windows 事件循环**：`main.py` 顶部必须在 import 阶段就切 `WindowsSelectorEventLoopPolicy`，否则 psycopg 异步直接报错。
2. **CORS**：`allow_origins=["*"]` 与 `allow_credentials=True` 同时开会被引擎拒绝——当前代码就是这样，属遗留问题，生产需改成显式域名白名单。
3. **连接串两套**：asyncpg 走 SQLAlchemy 管 `users` 表；psycopg3 裸连接走 LangGraph Checkpointer。别合并。

---

## 6. 阶段 4：LLM 服务层与 Prompt 工程

这一层是整个项目的"内容质量来源"，值得单独一轮，甚至几轮迭代。

### 给 AI 的提示词

```text
# 任务：实现 app/services/llm_service.py —— 所有 LLM 调用的唯一定点

# 上下文
- 用 langchain_openai.ChatOpenAI，base_url 指向火山方舟 OpenAI 兼容端点
- 需要三个能力：生成选题、写文章（要流式）、从文章提取配图要点

# 设计要求
1. 双模型三温度（全部从 .env 读，代码里给默认值）：
   - llm        = LLM_MODEL       (写作，temperature 0.7)
   - llm_fast   = LLM_MODEL_FAST  (选题，temperature 0.7)
   - llm_extract= LLM_MODEL_FAST  (提取，temperature 0.4，要稳定)
   三个都懒加载（@property + 私有字段），不要 __init__ 里全建
2. 三套 System Prompt 写成类常量，内容如下（可直接用，也可帮我改得更狠一点）：
   - TOPIC_SYSTEM_PROMPT：小红书爆款标题专家，5 条标题公式
     （数字+痛点 / 悬念反转 / 情绪共鸣 / 身份代入 / 对比冲击），15 字内，口语化，可用 emoji
   - ARTICLE_SYSTEM_PROMPT：800-1200 字，开头抓人、干货、口语化、小标题、结尾引导评论
   - VISUAL_SYSTEM_PROMPT：提取 3 条纯视觉描述，第一条是封面，禁文字、禁敏感内容，
     风格=插画/扁平化/简约现代/温馨治愈
3. plan_topics 用 with_structured_output(TopicsResponse, include_raw=True)，
   **必须写降级方案**：结构化失败时改成"在 prompt 里追加 JSON 格式说明 + 正则剥 ```json 块 + json.loads"
4. stream_write_draft_with_usage：astream 逐块收集，支持 on_chunk 回调，
   同时从 usage_metadata / response_metadata.token_usage 里取 token；
   取不到时按 len(text)//2 估算（注明这是估算）
5. extract_visual_points：文章超长先截断到 1500 字，按行解析并去掉 "1. " 这类编号前缀，最多取 3 条
6. 所有调用统一挂上 PII 脱敏 callback（app/core/callbacks.py 的 pii_callback），延迟导入避免循环依赖
7. 文件末尾导出单例 llm_service

# 输出
完整文件 + 一段"如何只跑这一层做验证"的说明（命令行直接调用三个方法各一次）
```

### Prompt 迭代的正确姿势

写完不要急着往下走，用这个提示词单独调优：

```text
我用你的 ARTICLE_SYSTEM_PROMPT 跑了 3 个不同选题，结果如下：
<粘贴 3 篇输出>

问题：
1. 开头都在复述选题，不够抓人
2. emoji 太多，每 2 句一个
3. 结尾的互动引导每次都是同一句"你觉得呢"

请只改 System Prompt（不要改代码结构），给出新版全文 + 你改了哪几处、为什么。
改完我用同样 3 个选题复测。
```

> 有 LangSmith 的话，直接把 trace 链接给它，比贴文本高效。

---

## 7. 阶段 5：LangGraph 编排层（项目核心）

### 给 AI 的提示词（一次只给一个文件，建议分 3 轮）

**第 1 轮 —— 状态定义**

```text
# 任务：定义 app/graph/state.py
遵守 PROJECT_RULES.md。

用 TypedDict(total=False) 定义 AgentState，覆盖：
- 选题：topic_direction / generated_topics(list[str]) / selected_topic
- 写作：article_content / review_feedback / review_status / revision_count
- 视觉：visual_points(list[str]) / image_urls(list[str])
- 元数据：status / error / node_metrics

额外定义：
- NodeMetric 结构：node_name / duration_ms / start_time / end_time /
  input_tokens / output_tokens / total_tokens / model
- INITIAL_STATE 初始字典

# 硬约束
- node_metrics 是普通 list，**不要**用 add 型 reducer（因为我们要全量合并，
  merge_metrics(existing, new) 负责追加），请注释说明这个取舍
- 每个字段写中文注释说明由哪个节点写入
```

**第 2 轮 —— 三个 AI 节点**

```text
# 任务：实现 app/graph/nodes/ 下三个纯 AI 节点
- planner.py   plan_topics_node：调 llm_service.plan_topics，取 topic.title 列表，status="topics_generated"
- writer.py    write_draft_node：有 feedback 时 revision_count += 1；
               调 stream_write_draft_with_usage 流式收集完整内容；status="draft_generated"
- visualizer.py extract_visuals_node（提取 3 条要点）
                generate_images_node（并行生图）

# 硬约束
1. 节点全是 async def，签名 (state: AgentState) -> dict，只返回"要更新的字段"
2. 每个节点用 app/graph/metrics.py 的 MetricsContext 包住 LLM 调用，
   with 块自动计时，结束后 merge_metrics(state.get("node_metrics"), tracker.metrics)
3. generate_images_node：生图失败**不能**中断流程，部分失败也算完成，
   status 仍置 "completed"，失败信息写进 error
4. 用 app/core/logger.py 的 app_logger 打业务事件日志（中文语义化方法）
5. nodes/__init__.py 里统一导出，并在注释里写明：人工节点不在这里
   （在 workflow.py 和子图里），nodes/ 只放纯 AI 节点
```

**第 3 轮 —— 主图 + 子图 + 中断**

```text
# 任务：实现工作流图与人工中断
文件：app/graph/workflow.py、app/graph/subgraphs/topic_selection.py

# 拓扑
START → topic_selection(子图) → write_draft → human_review →
   approve: extract_visuals → generate_images → END
   reject : 回到 write_draft（回环，revision_count 递增）

# 硬约束（这些都是 LangGraph 1.0 的坑，必须遵守）
1. 用 interrupt(payload) 实现暂停，**不要**用 interrupt_before 参数（1.0 已废弃该用法）
2. 人工节点返回 Command(update={...}, goto="extract_visuals" | "write_draft") 做路由，
   **不要**用 add_conditional_edges
3. 选题逻辑封装成子图 topic_selection（plan_topics → human_select_topic 中断），
   子图编译**不带 checkpointer**，由主图统一挂
4. get_compiled_graph() 编译时挂 checkpointer；get_graph() 用全局单例缓存编译结果
5. interrupt 的 payload 里必须带 "action_required": "select_topic" / "review"，
   接口层要靠这个字段判断给前端渲染什么
6. human_review 的 payload 带 article_preview（正文截断 500 字）和 options=["approve","reject"]

# 输出
两个文件 + 一段"不用 HTTP、直接用 python -m asyncio 跑通一次完整流程"的验证脚本说明
```

### 本阶段必须理解的机制（教程讲解重点）

```
暂停：节点里 interrupt(payload) → payload 存进 checkpoint 的 tasks[*].interrupts[*].value
读取：接口层 extract_interrupt_info() 从 state_snapshot 里捞出 payload → 返回前端
恢复：graph.ainvoke(Command(resume={...}), config) → interrupt() 的返回值就是 resume 内容
分叉：审稿节点返回 Command(goto=...) 决定去 extract_visuals 还是回 write_draft
```

> 一句话总结给读者：**LangGraph 的 `interrupt()` 让"人"变成了一个可以被序列化进数据库的待办事项**。服务重启、隔几小时再回来，都还能接着走。

---

## 8. 阶段 6：持久化与多用户

### 给 AI 的提示词

```text
# 任务一：Checkpointer（app/graph/utils.py）
用 AsyncPostgresSaver 持久化图状态。

# 硬约束（这里是全项目最容易卡住的地方）
1. setup() 必须先用一条 autocommit 的独立连接执行，
   因为 CREATE INDEX CONCURRENTLY 不能在事务块里跑
2. setup 完再建 AsyncConnectionPool(min_size=1, max_size=10, open=False)，
   然后 await pool.open()，把 pool 交给 AsyncPostgresSaver
3. 提供 setup_checkpointer / get_checkpointer / close_checkpointer，全局单例

# 任务二：用户与认证
- app/models/user.py：User 模型（UUID 主键、username 唯一索引、password_hash、时间戳）
- app/core/security.py：密码哈希（argon2 优先，bcrypt 兜底）、JWT 签发与解码
- app/api/v1/auth.py：/auth/register、/auth/login、/auth/me
- app/dependencies/auth.py：HTTPBearer；get_current_user（解码→查库→401）

# 任务三：多租户隔离
- thread_id 用 f"{user.id}_{uuid4()}"
- 所有线程级接口先校验 thread_id.startswith(str(current_user.id))，否则 403/404
```

### 已知遗留（教程里可以作为"找茬练习"）

- `/threads` 与 `DELETE /threads/{id}` 用了裸 SQL 直接操作 `checkpoints` / `checkpoint_blobs` / `checkpoint_writes`，与 LangGraph 内部表强耦合，升级有风险。
- 删除没有二次确认、没有软删。

---

## 9. 阶段 7：HTTP 接口层与 SSE 流式

### 给 AI 的提示词

```text
# 任务：实现 app/api/v1/workflow.py（本项目最核心的接口文件）

# 接口清单
POST   /workflow/start                 启动工作流，跑到选题中断点，返回 5 个选题
GET    /workflow/state/{thread_id}     状态快照：status/values/next_nodes/is_completed/interrupt_info/node_metrics
POST   /workflow/resume/{thread_id}    恢复：action ∈ select_topic | approve | reject
GET    /workflow/history/{thread_id}   aget_state_history，最多 20 条
GET    /workflow/threads               当前用户的线程列表
DELETE /workflow/threads/{thread_id}   删除线程
POST   /workflow/stream/resume/{thread_id}  SSE 流式恢复（仅 select_topic / reject）

# 硬约束
1. 中断负载读取：LangGraph 1.0 的中断信息在
   state_snapshot.tasks[*].interrupts[*].value，写 extract_interrupt_info() 统一解析
2. 恢复时构造 Command(resume=payload) 传给 ainvoke
3. SSE：用 graph.astream_events(..., version="v2")，监听
   on_chat_model_start / on_chat_model_stream / on_chat_model_end，
   把 token 逐块推给前端；事件类型固定 7 种：start / resume / llm_start / llm_token /
   llm_end / done / error
4. 响应头加 X-Accel-Buffering: no，防止 Nginx 缓冲导致前端收不到流式数据
5. token 统计从 usage_metadata 或 response_metadata.token_usage 里取
6. 每个线程级接口先做越权校验（thread_id 前缀 = 用户 id）
7. 每个接口写清楚 docstring，错误返回要有可读的中文 detail
```

### 前端对应的 SSE 解析（教程要讲）

前端**没有**用 EventSource（因为要带 Authorization 头），而是 `fetch` + `ReadableStream` 手写按 `data: ` 分行解析 JSON——这一段在 `frontend/src/api.js` 的 `handleSSEStream`，是全项目唯一"手写协议解析"的地方，值得单独讲一集。

---

## 10. 阶段 8：配图生成服务

### 给 AI 的提示词

```text
# 任务：实现 app/services/image_service.py

# 调用方式
用 volcenginesdkarkruntime.AsyncArk，调用 images.generate，参数：
model=IMAGE_MODEL(接入点ID) / prompt / size=IMAGE_SIZE(2K) / response_format="url" /
watermark=True / sequential_image_generation="disabled"

# 硬约束（全是踩过的坑）
1. 返回的 URL **有时效**，必须立刻用 httpx 下载并落盘到
   static/images/generated/xhs_{时间戳}_{8位uuid}.png，返回静态访问路径 /static/images/generated/xxx.png
2. 失败重试一次：换一条随机的 FALLBACK_PROMPTS
3. 批量生图用 asyncio.gather 并发
4. API Key 优先读 ARK_API_KEY，缺省回退 LLM_API_KEY
5. 提示词模板：套一层小红书风格（插画/扁平/柔和色调/留白/无文字），
   把视觉要点 + 风格词拼起来
6. 另开一个测试接口 POST /image/generate（app/api/v1/image.py），
   方便不开工作流也能验证生图链路
```

---

## 11. 阶段 9：前端操作台

### 给 AI 的提示词

```text
# 任务：实现 frontend/（Vue 3 + Vite 单页）

# 依赖
vue ^3.4 / axios ^1.6 / vite ^5 / @vitejs/plugin-vue（不要引入 UI 库，手写 CSS）

# 配置
vite.config.js：dev 端口 3000，把 /api 和 /static 代理到 http://localhost:8000

# 界面要求（一个 App.vue 搞定，不要拆组件）
1. 登录 / 注册卡片（未登录时显示）
2. 左侧线程侧边栏：列表、切换、删除
3. 右侧 4 步向导：① 选题 ② 写作 ③ 审核 ④ 配图
   - 第①步：展示 5 个选题卡片，点击即选定
   - 第②步：文章**逐字流式渲染**（接 SSE）
   - 第③步：通过 / 驳回（驳回要填修改意见）
   - 第④步：展示生成的图片网格
4. 底部：流式事件日志面板 + 节点耗时与 token 统计卡片

# src/api.js 要求
- axios 实例 baseURL=/api/v1，超时 120s
- Token 存 localStorage；请求拦截器自动加 Bearer
- 响应拦截器：401 时清 Token 并派发 auth:logout 事件
- SSE 用原生 fetch + ReadableStream 手写解析（因为 EventSource 不能带自定义头），
  按 data: 分行 JSON.parse，映射 7 种事件到回调

# 硬约束
- 全程用中文文案
- 流式渲染时用 nextTick 保持滚动到底部
```

---

## 12. 阶段 10：可观测性加固

### 给 AI 的提示词

```text
# 任务：给项目加三层可观测性

1. 结构化日志 app/core/logger.py
   - structlog；TimedRotatingFileHandler 按天轮转保留 30 天
   - 文件恒为 JSON，控制台彩色
   - 自定义 processor 注入 request_id 和 service
   - 封装 AppLogger，提供约 20 个语义化方法：workflow_started / topic_selected /
     draft_approved / draft_rejected / node_completed 等
   - 导出全局 app_logger

2. PII 脱敏 app/core/pii_anonymizer.py + app/core/callbacks.py
   - 正则识别 6 类：邮箱 / 信用卡 / API Key(含 OpenAI、LangSmith、UUID 格式) /
     中国手机号 / IP / 身份证
   - 4 种策略：redact / mask / hash / block
   - anonymize_dict 支持递归
   - 做成 LangChain BaseCallbackHandler，在 on_llm_start / on_chat_model_start /
     on_llm_end 时脱敏，保证 LangSmith 里不落敏感信息

3. 业务指标 app/graph/metrics.py
   - NodeMetricsTracker + MetricsContext（with 块自动计时）+ LLMUsage + merge_metrics
   - 每个节点往 state["node_metrics"] 追加一条
   - 前端汇总展示总耗时与总 token
```

---

## 13. 阶段 11：联调验收

### 一次完整跑通的校验清单

```bash
# 后端
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# 前端
cd frontend && npm run dev
```

1. 注册账号 → 登录，拿到 Token。
2. `POST /api/v1/workflow/start {"topic_direction":"AI技术"}` → 返回 5 个选题 + `interrupt_info.action_required = select_topic`。
3. 前端点选一个选题 → SSE 流式出文章（验证逐字渲染 + token 统计）。
4. 写完后停在审稿中断 → 驳回并填意见 → 验证 `revision_count` 递增、文章重写。
5. 通过 → 提取 3 条配图要点 → 生成 3 张图 → 落盘 `static/images/generated/`。
6. **重启后端服务**，再 `GET /workflow/state/{thread_id}` → 状态还在（验证持久化）。
7. 打开 LangSmith，确认每次 LLM 调用都可见、且 Key 已被脱敏。

### 让 AI 做验收的正确提示词

```text
我要做一次端到端联调。请你给我一份"分步验证清单"：
每一步写清楚 调用哪个接口/点哪个按钮、预期看到什么、如果不符合预期最可能的原因是什么。
我会把每一步的实际结果贴回来，你只回答"通过 / 不通过 + 下一步"。
```

---

## 14. 当前完成状态（截至 2026-09-27）

### 已完成

- [x] LangGraph 主图 + 选题子图，中断/恢复/回环全部可用
- [x] PostgreSQL 持久化（Checkpointer），重启可恢复
- [x] 双模型三温度 + 三套 System Prompt + 结构化输出降级
- [x] 8 个 HTTP 接口 + SSE 流式文章生成
- [x] JWT 注册登录 + 多租户线程隔离
- [x] 火山方舟 Seedream 生图 + 落盘
- [x] Vue3 四步向导 + 流式渲染 + 指标卡片
- [x] structlog + PII 脱敏 + 节点指标 + LangSmith 追踪
- [x] 实际产出过 10 张配图（`static/images/generated/`）

### 未收尾（可作为教程的"进阶作业"）

| 问题 | 严重度 | 建议动作 |
|---|---|---|
| `.env.example` 和 `test_db_connection.py` 里有真实密钥/密码 | 高 | 改占位符，并从 git 历史清除 |
| CORS `*` + `allow_credentials=True` 并存 | 高 | 改显式域名白名单 |
| `jwt_secret_key` 有硬编码默认值 | 高 | 生产必须环境变量覆盖 |
| `/threads` 裸 SQL 依赖 LangGraph 内部表 | 中 | 抽一层仓储或改用官方 API |
| `image_service` 模块级单例，缺 Key 时 import 即抛错 | 中 | 改懒加载 + 启动显式校验 |
| `App.vue` 1216 行单文件，vue-router 装了没用 | 中 | 按视图拆分 |
| README 严重过时（库名、目录、文件清单都错） | 中 | 用本文件重写 |
| 零测试、无 CI | 低 | 补 `tests/`（AI 写测试很快） |
| 日志与图片目录无清理策略 | 低 | 加定时清理 |

### 当前技术事实速查（README 已过时，以此为准）

- 后端就在仓库根目录，**不是** `backend/`
- 数据库名 `langgraph_db`（不是 `aicontent`）
- **不存在** `app/graph/nodes/human.py`；两个人工节点在 `workflow.py` 和 `subgraphs/topic_selection.py`
- 固定生成 **5** 个选题
- 生图接入点 `ep-20260923014947-j8fcl`

---

## 15. 附录：可复用的"AI 编码"提示词模板

### A. 日常改代码

```text
遵守 PROJECT_RULES.md。

# 本次任务
<一句话>

# 相关文件（先读完再动手）
- <路径1>
- <路径2>

# 硬约束
- <不许改什么 / 必须用什么写法>

# 完成后必须回答
1. 改了哪些文件
2. 怎么验证（命令或点击路径）
3. 有没有引入新的风险
```

### B. 报错修复（最高效的用法）

```text
遵守 PROJECT_RULES.md。

# 现象
<贴完整报错 traceback，不要自己删>

# 我刚才做的事
<一句话>

# 相关文件
<路径>

# 要求
先判断根因，再说改法。如果是你对框架 API 记错了，直接承认并去查官方文档，
不要靠猜。改完告诉我为什么之前会错。
```

### C. 让 AI 写文档

```text
遵守 PROJECT_RULES.md。

请通读全仓库，产出 PROJECT_ANALYSIS.md，包含：
项目定位 / 技术栈表（带版本）/ 分层架构图 / 每个文件的职责 /
核心机制深挖（挑 3-4 个）/ 关键调用链路 / 问题与改进建议（分高中低优先级）/ 总结。

要求：只描述代码里真实存在的东西，不要写"应该有"。
发现文档与代码不一致时，明确指出哪一处错了。
```
