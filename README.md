# WebModbusTerm

**Modbus Monitor and Management Toolchain** - a GTKTerm-style serial + Modbus web terminal.

Open: `http://<host>:8088`

License: [MIT](LICENSE) - see [NOTICE](NOTICE) for fonts and logo attribution.

## Features

- Mode dropdown: Raw serial / Modbus RTU / Modbus TCP
- Load connection YAML (`configs/*.yml`)
- Raw + predefined commands with shared HEX / ending / CRC tools
- CRC modes: MODBUS, N/A, 0x0000, 0x00, 0xFFFF, 0xFF, SUM8, XOR8
- Manage `commands.yml` (CRUD, YAML/CSV import, download)
- Traffic log: Time / Action / HEX / ASCII with buffer size control
- Live WebSocket RX/TX
- Fully offline UI (local fonts, logo, CSS/JS - no CDN)

## Quick start

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux:   source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Then open http://127.0.0.1:8088

## YAML

**Connection** - `configs/modbus-rtu-demo.yml`:

```yaml
name: Modbus Device
connection:
  mode: raw
  port: /dev/ttyUSB0
  baudrate: 38400
  parity: E
```

**Commands** - `configs/commands.yml`:

```yaml
commands:
  - id: read_status
    title: Read Status
    value: 01 03 00 00 00 0A
    encoding: hex
```

## Install (Linux service)

Portable install - **venv + systemd** only (no apt/pacman for app deps).
Installs to `/opt/webmodbusterm` and adds a global `webmodbusterm` command.

```bash
sudo bash deploy/install.sh
# optional custom path:
# sudo PREFIX=/opt/webmodbusterm bash deploy/install.sh
```

CLI:

```bash
webmodbusterm help
webmodbusterm status
webmodbusterm logs
webmodbusterm start
webmodbusterm stop
webmodbusterm restart
webmodbusterm run
webmodbusterm open
```

## Notes

- Version: **1.0.0** (see `VERSION` and `CHANGELOG.md`)
- HEX mode accepts only `0-9 A-F` and spaces
- Binds `0.0.0.0:8088` (LAN / VPN friendly)
- Modbus logo is derived from Wikimedia Commons; trademark rules still apply (see `NOTICE`)
