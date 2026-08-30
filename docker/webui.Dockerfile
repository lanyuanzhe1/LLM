# services/webui 服务镜像：登录/聊天/知识库代理 + SPA 静态托管
# build context 必须是仓库根：docker build -f docker/webui.Dockerfile .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/webui/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/webui/webui/ webui/

EXPOSE 8080
CMD ["python", "-m", "uvicorn", "webui.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
