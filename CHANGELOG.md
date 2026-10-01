# Changelog

All notable changes to **WebModbusTerm** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-01

### Added
- Initial public release of **WebModbusTerm**
- FastAPI + Uvicorn web app on `0.0.0.0:8088`
- Connection modes: Raw serial, Modbus RTU, Modbus TCP
- Serial bridge with pyserial / pymodbus
- YAML connection profiles under `configs/`
- Predefined commands in `configs/commands.yml` with CRUD API
- YAML / CSV command import (replace or merge) and download
- Web UI: setup, traffic console, raw send, predefined send, Modbus execute
- Live WebSocket RX/TX streaming
- CRC / trailer modes: MODBUS, N/A, 0x0000, 0x00, 0xFFFF, 0xFF, SUM8, XOR8
- Shared HEX / ending / CRC tools for raw and predefined sends
- Traffic log columns: Time / Action / HEX / ASCII with buffer control
- Fully offline UI with bundled IBM Plex fonts (no CDN)
- Content-Security-Policy headers for self-hosted assets only
- Portable Linux installer (`deploy/install.sh`) and global `webmodbusterm` CLI
- systemd unit `webmodbusterm.service`
- MIT license; NOTICE for fonts and Modbus logo attribution
