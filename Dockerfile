# syntax=docker/dockerfile:1.7
# Build and scan only in authorized GitHub Actions; never on the deployment host.
ARG PYTHON_BASE=python:3.12-slim-bookworm@sha256:0f086103b026048cc50cb5da25ec435c023c5241a83fc44daea593377abc61c4
FROM ${PYTHON_BASE} AS wheels
WORKDIR /build
COPY requirements.lock.txt /build/requirements.lock.txt
# CPU wheel versions and hashes are locked for Python 3.12 Linux amd64.
# The base image is digest pinned; no source distributions are built.
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r /build/requirements.lock.txt

FROM ${PYTHON_BASE} AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 CITERAG_OFFLINE=1 \
    CITERAG_MODEL_CACHE_DIR=/app/data/models
WORKDIR /app
COPY requirements.lock.txt /app/requirements.lock.txt
COPY --from=wheels /wheels /wheels
RUN python -m pip install --no-index --no-cache-dir --find-links=/wheels \
    -r /app/requirements.lock.txt && rm -rf /wheels \
    && mkdir -p /app/data /app/config /app/docs \
    && chown -R 65532:65532 /app/data /app/config
COPY --chown=65532:65532 citerag /app/citerag
COPY --chown=65532:65532 docs /app/docs
COPY --chown=65532:65532 tasks /app/tasks
COPY --chown=65532:65532 configs /app/configs
USER 65532:65532
EXPOSE 18761 18762
CMD ["python","-m","citerag.web"]
