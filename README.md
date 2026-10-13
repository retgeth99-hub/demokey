# PubMed 科研情报分析

一个面向科研人员的文献情报分析 Demo：输入研究关键词后，系统检索 PubMed，统计年度趋势与地区分布，归纳研究方向，生成可解释的代表文献排名，并使用 DeepSeek 生成带 PMID 证据的中文综述。

## 技术栈

- 前端：React 19、TypeScript、Vite、原生 CSS、Nginx
- 后端：FastAPI、SQLAlchemy 2、Pydantic、HTTPX
- 数据库：PostgreSQL 17、Alembic
- 外部服务：NCBI PubMed E-utilities、DeepSeek API
- 部署：Docker Compose

## 最快启动方式

需要预先安装 Docker Desktop，并确保 5173、8000、5432 端口未被占用。

### Windows

最简单的方式是双击：

```text
start.cmd
```

也可以在 PowerShell 中执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

脚本会在缺少 `.env` 时自动从 `.env.example` 创建一份，然后构建并启动前端、后端和 PostgreSQL。

### macOS / Linux

```bash
cp .env.example .env
docker compose up --build -d
```

启动完成后访问：

- 系统网页：http://127.0.0.1:5173/
- API 文档：http://127.0.0.1:8000/docs
- 后端就绪检查：http://127.0.0.1:8000/health/ready

首次构建需要下载基础镜像和依赖，通常需要几分钟。

## API 密钥配置

系统不携带任何真实密钥。若需要完整体验，请编辑 `.env`：

```dotenv
NCBI_API_KEY=你的_PubMed_API_Key
NCBI_EMAIL=你的邮箱
DEEPSEEK_API_KEY=你的_DeepSeek_API_Key
```

- PubMed API Key 推荐配置，但不是启动服务的必需项。未配置时会自动按较低请求频率访问 PubMed。
- DeepSeek API Key 可选。未配置或模型调用失败时，系统会降级生成确定性模板报告，其他统计分析仍可完成。
- `.env` 已加入忽略规则，不要将真实密钥提交或转发。

## 常用命令

```powershell
# 查看服务状态
docker compose ps

# 查看后端日志
docker compose logs -f app

# 停止但保留数据库数据，也可以直接双击 stop.cmd
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop.ps1

# 停止并删除容器，仍保留数据库卷
docker compose down
```

如需删除本地演示数据，可执行 `docker compose down -v`。该命令会永久删除 PostgreSQL 数据卷，请谨慎使用。

## 本地开发

后端：

```powershell
uv sync
docker compose up -d postgres
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

前端：

```powershell
cd frontend
npm ci
npm run dev
```

开发环境前端地址仍为 http://127.0.0.1:5173/，Vite 会将 `/api` 和 `/health` 转发到 FastAPI。

## 测试与质量检查

```powershell
uv run ruff check .
uv run pytest
cd frontend
npm run typecheck
npm run build
```

## 核心流程

1. 用户提交关键词、年份、语言、文献类型和样本规模。
2. FastAPI 创建分析记录和持久化任务，立即返回任务 ID。
3. 后台工作器调用 PubMed ESearch、EFetch 和 ELink。
4. 系统规范化文献元数据，计算年度、地区、主题和代表性评分。
5. DeepSeek 根据受约束的证据包生成中文报告；异常时自动降级。
6. 前端轮询任务状态并呈现统计图表、文献评分和 PMID 证据链。

## 数据口径

- “代表文献”是系统的可解释综合评分，不等同于期刊影响因子或学术权威排名。
- 国家/地区根据第一作者首个单位地址推断，不代表研究实际发生地。
- PubMed 的 cited-in 关系覆盖不完整，因此引用信号只作为辅助特征。
- 报告由 AI 或模板生成，不能替代系统综述、Meta 分析或医疗建议。

更详细的需求、架构和数据库说明位于 [`docs`](docs) 目录。
