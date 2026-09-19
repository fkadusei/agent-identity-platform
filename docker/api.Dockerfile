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
# `spiffe` for the Workload API client: the api holds an SVID (S7).
RUN pip install --no-cache-dir "/workspace/sdk[spiffe]"
COPY app /workspace/app
COPY --from=web /web/dist /workspace/app/web/dist
ENV PYTHONPATH=/workspace
ENV WEB_DIR=/workspace/app/web/dist
RUN useradd --uid 1000 --create-home app
USER app
# The git revision this image was built from. scripts/check-images.sh compares it
# with HEAD, so "it works on kind" can be checked rather than assumed.
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA

CMD ["python", "-m", "app.api.main"]
