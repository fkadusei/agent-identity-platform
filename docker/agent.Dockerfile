# Build context = repo root:
#   docker build -f docker/agent.Dockerfile -t agent-platform/agent:demo .
FROM python:3.13-slim
WORKDIR /workspace
COPY requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt
COPY sdk /workspace/sdk
RUN pip install --no-cache-dir "/workspace/sdk[spiffe]"
COPY app /workspace/app
ENV PYTHONPATH=/workspace
RUN useradd --uid 1000 --create-home app
USER app
CMD ["uvicorn", "app.agent.service:app", "--host", "0.0.0.0", "--port", "8081"]
