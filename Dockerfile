# Stage 1: build the SPA
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: the app
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY docintel/ ./docintel/
COPY scripts/ ./scripts/
COPY --from=web /web/dist ./frontend/dist
RUN useradd -m app && mkdir -p /app/data && chown -R app /app
USER app
EXPOSE 8080
# --proxy-headers: Cloud Run terminates TLS; the app must see https:// for the OAuth redirect to match
CMD ["uvicorn", "docintel.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]
