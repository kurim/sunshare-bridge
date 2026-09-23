# Stage 1: build the React UI (Node is only needed here, not at runtime).
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
# Only the sources: a host node_modules/ or dist/ copied along would overwrite the fresh install.
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/public ./public
COPY frontend/scripts ./scripts
COPY frontend/src ./src
RUN npm run build

# Stage 2: the bridge.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY --from=ui /ui/dist ./app/web

# Set by CI from the git tag/branch (see .github/workflows/ci.yml and CHANGELOG.md); "dev" for
# a plain local `docker compose up --build` with no build arg passed.
ARG VERSION=dev
ENV APP_VERSION=$VERSION
ENV PYTHONUNBUFFERED=1
EXPOSE 80 8099

CMD ["python", "-m", "app.main"]
