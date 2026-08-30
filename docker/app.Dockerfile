# app 服务镜像：FastAPI 粮储领域服务（本地编排器 + ChatDoc 知识库）
# build context 必须是仓库根：docker build -f docker/app.Dockerfile .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
# ChatDoc manifest（已在 git 跟踪）：app 启动必需，只读
COPY artifacts/chatdoc/base.json artifacts/chatdoc/base.json

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
