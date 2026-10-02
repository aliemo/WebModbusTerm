# Changelog

All notable changes to **WebModbusTerm** are documented in this file.

## [2.0.0] - 2026-10-02

### Added
- pip packaging (`pyproject.toml`, `pip install .` → `webmodbusterm`)
- Docker image + Compose (`Dockerfile`, `docker-compose.yml`)
- Local Debian/RPM builds via nfpm (`./packaging/build.sh nfpm`)
- Local builders: `./packaging/build.sh`, `./packaging/clean.sh`
- `WEBMODBUSTERM_CONFIG_DIR` for external YAML (Compose mounts `/data/configs`)

### Changed
- Package layout: `app/` → `webmodbusterm/` with embedded `static/`, `templates/`, `configs/`
- Single entry for packaging (`build.sh` stages nfpm internally; no separate `stage.sh`)
- systemd unit runs `.venv/bin/webmodbusterm`

## [1.0.0] - 2026-10-01

### Added
- Initial public release of **WebModbusTerm**
- FastAPI + Uvicorn web app on `0.0.0.0:8088`
- Connection modes: Raw serial, Modbus RTU, Modbus TCP
- Serial bridge with pyserial / pymodbus
- YAML connection profiles and `commands.yml` CRUD / import / download
- Web UI traffic console, CRC tools, WebSocket RX/TX
- Offline UI (bundled IBM Plex fonts), CSP headers
- Portable Linux installer (`deploy/install.sh`) and systemd unit
- MIT license; NOTICE for fonts and Modbus logo attribution
