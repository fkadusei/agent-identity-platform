# Build context = repo root:
#   docker build -f docker/api.Dockerfile -t agent-platform/api:demo .
#
# The API also serves the web UI, so the build has a Node stage that compiles
# the React app and copies its dist/ into the runtime image.
FROM node:22-alpine AS web
WORKDIR /web
COPY app/web/package.json app/web/package-lock.json* ./
RUN npm ci || npm install
COPY app/web/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /workspace
COPY requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt
COPY sdk /workspace/sdk
RUN pip install --no-cache-dir /workspace/sdk
COPY app /workspace/app
COPY --from=web /web/dist /workspace/app/web/dist
ENV PYTHONPATH=/workspace
ENV WEB_DIR=/workspace/app/web/dist
RUN useradd --uid 1000 --create-home app
USER app
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
