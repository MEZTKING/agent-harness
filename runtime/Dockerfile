# The phone runtime's two layers (runtime/README.md). Built per ABI by build.sh with
# `docker buildx build --platform linux/arm64|linux/amd64 --target base|roundtable --output type=tar`.

# -- the base layer: a small Debian with Python, git and Node ------------------------------------
ARG BASE_IMAGE=debian:bookworm-slim
FROM ${BASE_IMAGE} AS base
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv git ca-certificates curl nodejs npm ripgrep tar xz-utils procps less \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt/*.bin /var/cache/debconf/*-old /var/log/apt/* \
      /var/log/dpkg.log /usr/share/doc/* /usr/share/man/* /usr/share/info/* \
 && mkdir -p /workspaces /root/.roundtable /opt/roundtable \
 && printf '{"python": "%s", "node": "%s", "git": "%s"}\n' \
      "$(python3 -c 'import platform; print(platform.python_version())')" \
      "$(node --version | tr -d v)" "$(git --version | cut -d' ' -f3)" > /etc/roundtable-base.json

# -- Roundtable in its own virtual environment ---------------------------------------------------
FROM base AS venv
ARG ABI
COPY wheels-${ABI}/ /tmp/wheels/
# Every package comes as a wheel downloaded by build.sh for this ABI and Debian's Python
# (cryptography as a manylinux wheel, never compiled under emulation); nothing is fetched here.
RUN python3 -m venv /opt/roundtable/venv \
 && /opt/roundtable/venv/bin/pip install --no-cache-dir --no-index --find-links /tmp/wheels roundtable-hold \
 && /opt/roundtable/venv/bin/roundtable version \
 && rm -rf /tmp/wheels /root/.cache

# -- the roundtable layer: only /opt/roundtable -------------------------------------------------
FROM scratch AS roundtable
COPY --from=venv /opt/roundtable /opt/roundtable
