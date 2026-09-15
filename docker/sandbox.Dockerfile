# Build context = repo root:
#   docker build -f docker/sandbox.Dockerfile -t agent-platform/sandbox:demo .
#
# The sandbox stands in for a real CRM/orders/payments/ticketing API, so the
# tools' HTTP backend can be exercised without vendor credentials.
FROM python:3.13-slim
WORKDIR /workspace
COPY requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt
COPY sdk /workspace/sdk
RUN pip install --no-cache-dir /workspace/sdk
COPY app /workspace/app
ENV PYTHONPATH=/workspace
RUN useradd --uid 1000 --create-home app
USER app
# The git revision this image was built from. scripts/check-images.sh compares it
# with HEAD, so "it works on kind" can be checked rather than assumed.
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA

CMD ["uvicorn", "app.sandbox.app:app", "--host", "0.0.0.0", "--port", "8090"]
