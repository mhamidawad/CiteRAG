# syntax=docker/dockerfile:1.7
# Build and scan only in authorized GitHub Actions; never on the deployment host.
# Public DHI Community variants; pulls require authenticated free Docker ID access.
ARG PYTHON_BUILD_BASE=dhi.io/python:3.12-debian13-dev@sha256:506f5a7a28976a704e7cf3db9d31f7dc8a442107bafc826c598fe276b3f9822a
ARG PYTHON_RUNTIME_BASE=dhi.io/python:3.12-debian13@sha256:f4e39e19121ff570ab095182c87263746c441b3bcc01d49f8dc2993adf986468

FROM ${PYTHON_BUILD_BASE} AS wheels
WORKDIR /build
COPY requirements.lock.txt /build/requirements.lock.txt
# Python 3.12 Linux amd64 CPU wheels and their hashes are locked.
# Install into an isolated target; no build tools or wheel cache enter runtime.
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r /build/requirements.lock.txt \
    && python -m pip install --no-index --no-cache-dir --find-links=/wheels \
    --target=/runtime/app/python-packages -r /build/requirements.lock.txt \
    && mkdir -p /runtime/app/data/models /runtime/app/reports /runtime/app/config /runtime/app/docs \
    && chown -R 65532:65532 /runtime/app

FROM ${PYTHON_RUNTIME_BASE} AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 CITERAG_OFFLINE=1 \
    PYTHONPATH=/app/python-packages \
    CITERAG_MODEL_CACHE_DIR=/app/data/models
WORKDIR /app
# The runtime is shell-less and contains no Docker client or Docker socket.
# DHI's runtime already supplies libstdc++ for the pinned CPU Torch wheel.
COPY --from=wheels --chown=65532:65532 /runtime/app /app
COPY --chown=65532:65532 requirements.lock.txt /app/requirements.lock.txt
COPY --chown=65532:65532 citerag /app/citerag
COPY --chown=65532:65532 docs /app/docs
COPY --chown=65532:65532 tasks /app/tasks
COPY --chown=65532:65532 configs /app/configs
USER 65532:65532
EXPOSE 18761 18762
ENTRYPOINT []
CMD ["python","-m","citerag.web"]
