# legado-server — 本地书库服务（FastAPI + SQLite）
FROM python:3.11-slim

WORKDIR /app

# 依赖安装（利用层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝源码
COPY app ./app

EXPOSE 8086

# 启动：安装依赖（requirements 已在镜像内）→ 启动 uvicorn
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8086"]
