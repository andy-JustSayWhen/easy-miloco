FROM node:24-bookworm-slim

ARG MILOCO_RELEASE_ZIP_URL="https://github.com/andy-JustSayWhen/easy-miloco/releases/download/v0.5/easy-miloco-v0.5-windows.zip"
ARG MILOCO_VALIDATE_URL="https://raw.githubusercontent.com/andy-JustSayWhen/easy-miloco/main/docs/scripts/wsl-miloco-validate.sh"

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/root/.local/bin:/data/.local/bin:/data/.openclaw/bin:${PATH}"
ENV EASY_MILOCO_BUNDLED_RUNTIME_DIR="/opt/easy-miloco/runtime"
ENV EASY_MILOCO_BUNDLED_VALIDATE_SH="/opt/easy-miloco/wsl-miloco-validate.sh"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        iproute2 \
        lsof \
        procps \
        python3 \
        python3-venv \
        tar \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && npm install -g openclaw

COPY extract_release_payload.py /usr/local/bin/easy-miloco-extract-release-payload
RUN chmod +x /usr/local/bin/easy-miloco-extract-release-payload

COPY .build-payload/ /opt/easy-miloco/runtime/
RUN set -eux; \
    if [ -s /opt/easy-miloco/runtime/install.sh ] \
        && [ -s /opt/easy-miloco/runtime/manifest.json ] \
        && find /opt/easy-miloco/runtime -maxdepth 1 -type f -name 'miloco-linux-*.tar.gz' | grep -q . \
        && find /opt/easy-miloco/runtime -maxdepth 1 -type f -name 'miloco-openclaw-plugin-*.tgz' | grep -q .; then \
      echo "Using prebuilt Miloco runtime payload from Docker build context"; \
    else \
      echo "Prebuilt payload missing; downloading release zip: $MILOCO_RELEASE_ZIP_URL"; \
      find /opt/easy-miloco/runtime -mindepth 1 -maxdepth 1 -exec rm -rf {} +; \
      curl -fL --retry 3 --connect-timeout 20 -o /tmp/easy-miloco-release.zip "$MILOCO_RELEASE_ZIP_URL"; \
      easy-miloco-extract-release-payload /tmp/easy-miloco-release.zip /opt/easy-miloco/runtime; \
    fi \
    && chmod +x /opt/easy-miloco/runtime/install.sh \
    && curl -fL --retry 3 --connect-timeout 20 -o /opt/easy-miloco/wsl-miloco-validate.sh "$MILOCO_VALIDATE_URL" \
    && chmod +x /opt/easy-miloco/wsl-miloco-validate.sh \
    && rm -f /tmp/easy-miloco-release.zip

COPY entrypoint.sh /usr/local/bin/easy-miloco-nas-entrypoint
COPY perf_probe.py /usr/local/bin/easy-miloco-perf-probe
RUN chmod +x /usr/local/bin/easy-miloco-nas-entrypoint /usr/local/bin/easy-miloco-perf-probe

WORKDIR /data
ENTRYPOINT ["/usr/local/bin/easy-miloco-nas-entrypoint"]
