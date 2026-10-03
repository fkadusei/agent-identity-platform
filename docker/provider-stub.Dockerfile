# Build context = repo root:
#   docker build -f docker/provider-stub.Dockerfile -t agent-platform/provider-stub:demo .
#
# An OpenAI-compatible provider that runs in-cluster, so the gateway's hosted
# branch can be exercised without anyone's cloud key (S17). A test double, not a
# model. Point the gateway at it with LLM_PROVIDER=openai-compatible and
# LLM_BASE_URL=http://provider-stub:8080/v1 (see docs/llm-gateway.md).
FROM python:3.13-slim
WORKDIR /workspace
COPY requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt
COPY app /workspace/app
ENV PYTHONPATH=/workspace
RUN useradd --uid 1000 --create-home app
USER app
# The git revision this image was built from (scripts/check-images.sh).
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA

CMD ["uvicorn", "app.provider_stub.app:app", "--host", "0.0.0.0", "--port", "8080"]
