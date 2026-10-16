# Legado Server（本地书库）

## 项目概述
FastAPI + SQLite + Jinja2 的本地书库服务，为 Legado 阅读器提供书源，同时支持 Web 浏览。

## 技术栈
- 后端: Python 3.11 + FastAPI + aiosqlite
- 前端: Jinja2 模板 + 原生 JS + CSS 变量（支持深色/浅色主题）
- 数据库: SQLite（WAL 模式，FTS5 全文搜索）
- 部署: Docker Compose，端口 8086

## 目录结构
legado-server/                     源码根目录
                              Docker 运行目录（compose 数据持久化）
  app/main.py              FastAPI 入口 + lifespan
  app/deps.py              依赖注入（DatabaseManager/ScannerService/AIService/Templates）
  app/utils.py             共享工具函数（is_legado_client, validate_file_path）
  app/middleware.py         中间件（ErrorHandler + RequestLogging）
  app/auth.py              认证模块（会话管理、密码哈希、权限验证）

  app/database/            数据库层（Repository Pattern）
    __init__.py            DatabaseManager 统一入口 + 向后兼容方法
    connection.py          SQLite 连接管理 + WAL + schema 迁移
    books.py               BookRepository: 书籍 CRUD
    chapters.py            ChapterRepository: 章节 CRUD + 内容读取
    tags.py                TagRepository: 标签操作
    categories.py          CategoryRepository: 分类操作
    config.py              ConfigRepository: 配置 CRUD + 缓存
    corrections.py         CorrectionRepository: AI 纠错记录

  app/api/                 API 路由层（REST）
    __init__.py            api_router 统一注册
    books.py               /api/books 书籍 CRUD
    categories.py          /api/categories 分类管理
    tags.py                /api/tags 标签管理
    config.py              /api/config 配置 CRUD + 扫描 + 统计
    corrections.py         /api/corrections AI 纠错
    ai.py                  /api/ai AI 检测/修复/测试

  app/pages/               HTML 页面路由
    home.py                /, /search, /book/{id}, /cover/{id}, /settings

  app/legado/              Legado 书源路由
    source.py              /sources/text.json, /sources/audio.json, /sources/qr, /sources/export, /discover

  app/services/            业务服务层
    scanner.py             ScannerService: 统一管理 TXT + MP3 扫描器
    ai.py                  AIService: 统一管理 AI Corrector

  app/scanners/            扫描器实现
    txt_scanner.py         TXT 扫描（正则 + AI 提取）
    mp3_scanner.py         MP3 扫描（ID3 标签）

  app/ai/                  AI 实现
    corrector.py           AI API 调用（书名/分类/标签/章节/OCR）

  app/templates/           Jinja2 模板
    login.html              管理员登录页
  app/static/              CSS/JS 静态资源
  data/                    SQLite 数据库 + 上传文件

## 依赖清单（requirements.txt）
```
fastapi>=0.115,<1.0
uvicorn==0.52.4
aiosqlite>=0.20,<1.0
httpx>=0.27,<1.0
mutagen>=1.47,<2.0
chardet>=5.0,<6.0
jinja2>=3.1,<4.0
qrcode==8.2
pillow==12.3.0
```

## 数据库表
- books: 书籍（title, author, type, file_path, category, cover_path）
- chapters: 章节（book_id, chapter_number, title, start_line, start_byte）
- book_tags: 标签（book_id, tag，多对多）
- categories: 分类表（支持空分类预创建）
- tags: 标签表（支持空标签预创建）
- config: 配置（key, value, category）
- corrections: AI 纠错记录
- books_fts / chapters_fts: FTS5 全文搜索索引

## 配置项（config 表）
- book_dirs (general): 监控目录，JSON 数组 [{path, category}]
- page_size (general): 每页显示数量
- auto_scan (general): 启动时自动扫描
- book_source_url (general): 书源导出地址
- ai_api_base (ai): AI API 地址
- ai_api_key (ai): AI API 密钥
- ai_model (ai): AI 模型名
- ai_enabled_features (ai): 启用的 AI 功能列表
- chapter_patterns (scanner): 章节识别正则
- min_chapter_score (scanner): 章节最小分数
- regex_book_name_patterns (scanner): 书名识别正则
- regex_author_patterns (scanner): 作者识别正则

## AI 功能
- detect_chapters: AI 补充正则未匹配的章节
- fix_ocr: AI 修复前3000字的错别字
- merge_duplicates: AI 合并重复章节
- extract_book_name: AI 识别文件名+内容提取书名/作者
- extract_category: AI 自动分类（小说/文学/历史等）
- extract_tags: AI 自动打 3-5 个标签

AI 触发流程: 读取内容 -> fix_ocr -> extract_book_name -> 正则章节 -> detect_chapters -> merge_duplicates -> 入库 -> extract_category -> extract_tags

## 分类与标签
- 分类（Category）: 目录级别，添加目录时指定，一本书一个分类
- 标签（Tags）: 书籍级别，多对多，用户/AI 手动打

## API 端点
- GET / 首页（支持 category/tag 筛选）
- GET /settings 设置页
- GET /search?key= 搜索
- GET /book/{id} 书籍详情
- GET /api/books 书籍列表 API
- GET /api/categories 分类列表
- POST /api/categories 创建空分类
- POST /api/categories/rename 重命名分类
- DELETE /api/categories/{name} 删除分类
- GET /api/tags 标签列表
- POST /api/tags 创建空标签
- POST /api/tags/rename 重命名标签
- DELETE /api/tags/{name} 删除标签
- POST /api/tags/merge 合并标签
- POST /api/config/scan 触发扫描
- POST /api/config 更新配置
- POST /api/ai/test 测试 AI 连接
- GET /login 管理员登录页
- POST /login 登录验证
- GET /logout 退出登录
- GET /api/auth/status 认证状态
- POST /api/auth/change-password 修改密码
- GET /sources/text.json Legado 书源 JSON
- GET /sources/qr 书源二维码

## 部署信息
- 容器名: legado-server
- 端口: 8086
- 基础镜像: python:3.11-slim（无 Dockerfile，compose 中 command 运行时 pip install）
- 数据持久化: data/ 目录挂载到宿主机持久化路径
- 启动命令: `pip install -q -r /app/requirements.txt && uvicorn app.main:app --host 0.0.0.0 --port 8086`

---

## 改动日志

### 2026-09-14（管理员登录）
1. 新增 app/auth.py - 会话管理（Cookie + 内存存储）、密码哈希（PBKDF2）、登录验证
2. 新增 app/api/auth.py - 登录/退出/修改密码 API
3. 新增 app/templates/login.html - 登录页面
4. 修改 pages/home.py - /settings 页面需要登录才能访问
5. 修改 main.py - 注册 auth_router
6. 修改 settings.html - 添加管理员信息、退出按钮、修改密码表单
7. requirements.txt 补充 python-multipart（FastAPI Form() 必需）
8. 默认账号: admin / admin123

### 2026-09-13（依赖修复）
1. requirements.txt 补全缺失依赖 - 原文仅含 uvicorn/qrcode/pillow，缺少 fastapi/aiosqlite/httpx/mutagen/chardet/jinja2，导致容器启动时 uvicorn 无法加载 app.main 而反复重启

### 2026-06-05 22:21（后端第三轮优化）
1. legado/source.py - discover 端点改用 Repository 模式（get_books）替代直接 raw SQL，新增 per_page 参数校验（1-100），QR 端点增加 ImportError 处理
2. ai/corrector.py - 新增 retry 逻辑（max_retries=2），429 限流自动退避等待，401 认证失败直接抛出 ValueError，超时异常独立处理，结构化日志记录每次 API 调用
3. pages/home.py - 提取 VALID_PAGE_SIZES/DEFAULT_PAGE_SIZE 常量，page_size 校验不在允许范围内自动回退默认值，所有端点增加参数范围校验，cover 端点增加 book_id 校验
4. services/ai.py - 保持简洁委托模式，无需修改

### 2026-06-05 22:15（后端第二轮优化）
1. database/books.py - 统一 row_factory 设置在构造函数中，search 方法预计算 like_key 减少重复，exists 使用 LIMIT 1 优化
2. database/chapters.py - get_content 改为流式读取（逐行而非一次性加载整个文件），新增 FileNotFoundError/PermissionError 优雅处理，新增 get_content_range 方法用于预览
3. database/tags.py - merge 方法修复潜在冲突（先删除 target_tag 再 rename），get_books_by_tag 增加空结果检查
4. api/corrections.py - 使用 Pydantic Field 添加参数校验，统一 HTTPException 错误响应
5. api/ai.py - text_sample 添加长度校验（10-50000），区分超时/认证/通用异常，中文错误消息
6. api/categories.py - 使用独立的 CategoryCreate/CategoryRename Pydantic 模型替代通用 ConfigUpdate，分页参数使用 Query 校验
7. api/tags.py - 使用独立的 TagCreate/TagRename/TagMerge Pydantic 模型，merge 增加 source==target 校验

### 2026-06-05 21:35（后端代码优化）
1. 新增 middleware.py - ErrorHandlerMiddleware（统一异常捕获+JSON响应）+ RequestLoggingMiddleware（请求日志+耗时统计）
2. main.py 集成中间件 - 添加 ErrorHandlerMiddleware 和 RequestLoggingMiddleware，日志自动记录非健康检查请求
3. utils.py 增强 - 新增 sanitize_filename（安全文件名）、truncate_text（文本截断）、format_file_size（文件大小格式化）、safe_int（安全整数转换），is_legado_client 改用 any() 提高可读性
4. api/books.py 改进 - 使用 Pydantic Field 添加参数校验（search max_length=200, per_page 1-200），HTTPException 使用中文错误消息
5. api/config.py 改进 - 配置项 key 长度校验（1-100），批量更新限制最多50项，删除操作返回中文消息，异常统一使用 HTTPException
6. services/scanner.py 改进 - 新增 _scan_lock 防止并发扫描，scan_all 返回目录处理数，单目录扫描失败不影响其他目录，添加 scan_dir 返回布尔值

### 2026-06-05 21:28（CSS 设计系统 v4.0 升级）
1. CSS 设计系统 v4.0 - 全面重构毛玻璃设计系统，新增动画装饰光球浮动（orbFloat 25s/30s 周期）、模态框弹入动画（modalIn）、通知滑入方向优化
2. 颜色系统扩展 - 新增 --accent-rgb、--success/--danger/--warning 语义颜色变量
3. 阴影层次细化 - 新增 --shadow-xs 和 --shadow-xl，5 级阴影体系
4. 圆角系统完善 - 新增 --radius-xs（6px）和 --radius-full（药丸形），6 级圆角体系
5. 交互动效增强 - 按钮 hover 上浮+阴影扩大、卡片 hover 上移 6px、章节列表 hover 缩进动画、Logo hover 旋转缩放
6. 表单体验提升 - 输入框 focus 发光环、边框加粗到 1.5px、textarea 等宽字体
7. 移动端深度适配 - 设置页表单垂直堆叠、按钮组垂直排列、统计网格单列、模态框内边距缩减
8. 打印样式 - 新增 @media print，隐藏导航/分页/页脚/按钮
9. 无障碍增强 - prefers-reduced-transparency 降级保留
10. CSS 缓存破坏版本升级 - ?v=3.0 → ?v=4.0

### 2026-06-05 10:30（毛玻璃 UI 重构 + 正则设置卡片）
1. CSS 设计系统 v3 毛玻璃重构 - 全站启用 light-mode glassmorphism：渐变背景 + 3 个装饰光球（紫/绿/粉）提供 backdrop-filter 模糊源，所有卡片/面板/按钮统一毛玻璃
2. SVG 图标替换全部 emoji - 导航栏、设置页区段标题、按钮、首页/详情页/搜索页书籍占位符
3. 设置页排版优化 - 区段标题增加分隔线，按钮组统一 .btn-row 布局，AI 配置改为 .ai-field 行内 label+input
4. 正则识别设置卡片 - 新增独立区段，配置存储在 config 表，txt_scanner.py 从 DB 读取正则模式

### 2026-06-04（UI设计系统重构 + 导航栏优化）
1. CSS 设计系统 v5 - 新建完整设计系统，CSS 变量体系（亮色/暗色主题）、毛玻璃导航栏、hover 动画、响应式断点
2. 删除模板内联样式 - 所有样式统一由外部 style.css 管理
3. 导航栏隐藏按钮 - base.html 新增 ☰ 按钮，状态通过 localStorage 持久化
4. 缓存破坏机制 - CSS 链接添加版本号

### 2026-06-04（后端模块化重构）
1. 修复 ai_config 幽灵引用 - 删除废弃端点
2. 修复 db 未注入 bug - books.py 的 db 全局变量从未被 main.py 注入
3. database 层拆分 - 673 行单体 Database 类拆为 6 个 Repository + DatabaseManager 统一入口
4. 依赖注入统一 - 新建 deps.py 管理单例
5. API 层拆分 - 7 个独立模块
6. 页面路由分离 / Legado 路由分离
7. 服务层封装 + utils.py 抽取

### 2026-06-04（初始功能 + UI修复 + 数据库迁移）
- AI 功能 6 项接入扫描流程
- 分类/标签管理完整 CRUD
- 书源导出三种形式
- 数据库 categories/tags 表迁移
- 首页分类 Tab 展示 + 标签筛选 + 分页
