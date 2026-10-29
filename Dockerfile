FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend /app
COPY --from=ui /ui/dist /frontend/dist
RUN useradd --system --create-home espresso && mkdir -p /data/backups && chown -R espresso /data
USER espresso
ENV ENVIRONMENT=production ENABLE_SCHEDULER=1 ALLOW_SIMULATOR=0
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
