FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim AS runtime

ARG DEPTHMAPX_VERSION=v0.8.0
ARG INSTALL_BUILD_TOOLCHAIN=false
WORKDIR /app

RUN apt-get update -o Acquire::Retries=3 \
    && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libexpat1 \
    && if [ "$INSTALL_BUILD_TOOLCHAIN" = "true" ]; then apt-get install -y --no-install-recommends gcc; fi \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fL "https://github.com/SpaceGroupUCL/depthmapX/releases/download/${DEPTHMAPX_VERSION}/depthmapXcli_linux64" \
    -o /usr/local/bin/depthmapXcli \
    && chmod +x /usr/local/bin/depthmapXcli

ENV DEPTHMAPX_CLI_PATH=/usr/local/bin/depthmapXcli \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN pip install uv \
    && uv export --frozen --no-dev --format requirements-txt --no-hashes -o /tmp/requirements-docker.txt
RUN pip install -r /tmp/requirements-docker.txt

COPY core ./core
COPY modules ./modules
COPY router ./router
COPY share ./share
COPY store ./store
COPY static ./static
COPY templates ./templates
COPY utils ./utils
COPY main.py README.md ./
COPY --from=frontend-builder /app/static/frontend ./static/frontend

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
