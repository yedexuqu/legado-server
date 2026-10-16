# legado-server（本地书库）

为 [Legado 阅读器](https://github.com/gedoor/legado) 提供书源 + Web 浏览的本地书库服务。

FastAPI + SQLite(FTS5) + Jinja2 模板，纯 Python，无外部服务依赖。

## 特性

- 书籍 / 章节管理，SQLite WAL + FTS5 全文检索
- 为 Legado 阅读器提供书源接口（`/legado/*`）
- Web 界面浏览、搜索、深色/浅色主题
- txt / 有声书(mp3) 扫描入库
- 可选 AI 纠错（配置 `ai_api_key` 后启用，密钥保存在数据库，不入仓库）

## 目录结构

```
legado-server/
├── app/                  # 源码
│   ├── main.py           # FastAPI 入口 + lifespan
│   ├── deps.py           # 依赖注入
│   ├── auth.py           # 会话 / 密码哈希 / 权限
│   ├── utils.py          # 共享工具
│   ├── middleware.py     # 错误处理 / 请求日志
│   ├── ai/               # AI 纠错
│   ├── api/              # REST 路由
│   ├── database/         # Repository 数据层
│   ├── legado/           # Legado 书源接口
│   ├── pages/            # 页面路由
│   ├── scanners/         # txt / mp3 扫描
│   ├── services/         # 业务服务
│   ├── static/           # 静态资源
│   └── templates/        # Jinja2 模板
├── requirements.txt
├── Dockerfile
├── compose.yaml          # 部署编排（路径用占位符，见下）
└── PROJECT.md            # 详细设计文档
```

## 部署（Docker Compose）

> 编辑 `compose.yaml`，把 `<SOURCE_DIR>` / `<DATA_DIR>` / `<BOOKS_DIR>` 替换为你主机的真实路径。

```bash
# 1) 拉取镜像（或本地 build: docker build -t legado-server .）
docker pull ghcr.io/<owner>/legado-server:latest

# 2) 启动
docker compose up -d

# 3) 访问 Web： http://<host-ip>:8086
```

### 本地构建镜像

```bash
docker build -t ghcr.io/<owner>/legado-server:latest .
docker push ghcr.io/<owner>/legado-server:latest
```

## 配置

运行后在 Web **设置** 页配置：

- `ai_api_key`：AI 纠错用的 API 密钥（可选，留空则不启用 AI 纠错）
- 扫描目录、采集间隔等

> 注意：本仓库示例中的 `<owner>`、`<host-ip>`、卷路径均为占位符，请替换为你自己的环境值。
> 任何私有网络地址、密钥、个人路径均**不入库**。
