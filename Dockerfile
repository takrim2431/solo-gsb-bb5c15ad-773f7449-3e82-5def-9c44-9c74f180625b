FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLANNER_DB=/data/planner.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# 数据库目录（volume 挂载点）；启动时自动建表并写入示例目录
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# 启动入口：先初始化数据库，再启动 uvicorn
CMD ["sh", "-c", "python -m app.init_db && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
