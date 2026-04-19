# syntax=docker/dockerfile:1.7
#
# STC Framework — production image.
#
# Two-stage build. The builder stage installs only the extras named in
# the ``DEPLOYED_SUBSYSTEMS`` build argument. Disabled subsystems are
# not present in the final image — LaunchDarkly can only toggle what
# was actually installed. This is the "deploy gate" half of the
# two-layer feature-flag story; LaunchDarkly provides the runtime half.
#
# The image runs as an unprivileged user (uid 10001), exposes Flask on
# :8000 and Prometheus on :9090, and drains for 30 s on SIGTERM to
# match the ECS ``stop_timeout`` and the in-process
# ``_SystemRunner.shutdown(drain_timeout=30.0)``.

# --- builder ---------------------------------------------------------
FROM python:3.11-slim AS builder

ARG DEPLOYED_SUBSYSTEMS="service,litellm,redis,launchdarkly,otlp"
ARG GIT_SHA="unknown"

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY spec-examples ./spec-examples

RUN pip install --upgrade pip \
    && pip install -e ".[${DEPLOYED_SUBSYSTEMS}]"

# Download the spaCy model only if the presidio extra is present —
# a ~1 GB binary we don't want to pull into images that don't use it.
RUN if echo ",${DEPLOYED_SUBSYSTEMS}," | grep -q ",presidio,"; then \
        python -m spacy download en_core_web_sm ; \
    fi

# --- runtime --------------------------------------------------------
FROM python:3.11-slim AS runtime

ARG DEPLOYED_SUBSYSTEMS="service,litellm,redis,launchdarkly,otlp"
ARG GIT_SHA="unknown"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# curl is the only runtime apt dependency — the HEALTHCHECK uses it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -u 10001 -r -s /usr/sbin/nologin stc \
    && mkdir -p /app /mnt/audit /mnt/tokens /var/cache/ld \
    && chown -R stc:stc /mnt/audit /mnt/tokens /var/cache/ld

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /src/src /app/src
COPY --from=builder /src/spec-examples /app/spec-examples

WORKDIR /app
USER stc

EXPOSE 8000 9090

HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

LABEL org.stc.deployed_subsystems="${DEPLOYED_SUBSYSTEMS}" \
      org.stc.git_sha="${GIT_SHA}" \
      org.opencontainers.image.source="https://github.com/ambastha-nitesh/stc-framework" \
      org.opencontainers.image.licenses="Apache-2.0"

CMD ["gunicorn", \
     "-k", "gthread", \
     "--threads", "8", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "stc_framework.service.wsgi:application"]
