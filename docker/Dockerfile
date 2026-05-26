FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim

ARG DEPTHMAPX_VERSION=v0.8.0
WORKDIR /app

RUN printf '%s\n' \
    'Types: deb' \
    'URIs: https://mirrors.tuna.tsinghua.edu.cn/debian' \
    'Suites: trixie' \
    'Components: main' \
    'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' \
    '' \
    'Types: deb' \
    'URIs: https://mirrors.tuna.tsinghua.edu.cn/debian-security' \
    'Suites: trixie-security' \
    'Components: main' \
    'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' \
    > /etc/apt/sources.list.d/debian.sources \
    && apt-get update -o Acquire::Retries=3 \
    && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gcc \
    libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# Install depthmapX CLI
RUN curl -fL "https://github.com/SpaceGroupUCL/depthmapX/releases/download/${DEPTHMAPX_VERSION}/depthmapXcli_linux64" \
    -o /usr/local/bin/depthmapXcli \
    && chmod +x /usr/local/bin/depthmapXcli

ENV DEPTHMAPX_CLI_PATH=/usr/local/bin/depthmapXcli

COPY pyproject.toml ./
RUN python - <<'PY' > /tmp/requirements-docker.txt
import tomllib
from pathlib import Path

project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
for dependency in project["project"]["dependencies"]:
    print(dependency)
PY
RUN pip install --no-cache-dir -r /tmp/requirements-docker.txt

COPY . .
COPY --from=frontend-builder /app/static/frontend ./static/frontend

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
