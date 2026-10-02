# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="WebModbusTerm" \
      org.opencontainers.image.description="Modbus Monitor and Management Toolchain" \
      org.opencontainers.image.source="https://github.com/aliemo/WebModbusTerm" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="2.0.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WEBMODBUSTERM_HOST=0.0.0.0 \
    WEBMODBUSTERM_PORT=8088 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/webmodbusterm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE NOTICE VERSION requirements.txt ./
COPY webmodbusterm ./webmodbusterm
COPY run.py ./

RUN pip install --upgrade pip \
    && pip install .

EXPOSE 8088

# Mount host serial devices at runtime, e.g.:
#   docker run --device=/dev/ttyUSB0 -p 8088:8088 webmodbusterm
CMD ["webmodbusterm"]
