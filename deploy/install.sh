#!/usr/bin/env bash
# WebModbusTerm portable install (venv + systemd). No apt/pacman required for app deps.
set -euo pipefail

PREFIX="${PREFIX:-/opt/webmodbusterm}"
SERVICE_NAME="webmodbusterm"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}.service"
BIN_DST="/usr/local/bin/webmodbusterm"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need python3
need systemctl

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

# Optional read-only rootfs helpers (e.g. some appliance images)
if command -v rw >/dev/null 2>&1; then
  rw || true
fi

echo "Installing WebModbusTerm -> ${PREFIX}"
mkdir -p "${PREFIX}"

if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --exclude '.venv' \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    "${ROOT}/" "${PREFIX}/"
else
  mkdir -p "${PREFIX}"
  for item in app configs deploy static templates requirements.txt run.py VERSION README.md CHANGELOG.md LICENSE NOTICE; do
    if [[ -e "${ROOT}/${item}" ]]; then
      rm -rf "${PREFIX}/${item}"
      cp -a "${ROOT}/${item}" "${PREFIX}/${item}"
    fi
  done
fi

cd "${PREFIX}"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# Global CLI (works with custom PREFIX)
cat > "${BIN_DST}" <<EOF
#!/usr/bin/env bash
export WEBMODBUSTERM_HOME="${PREFIX}"
exec "${PREFIX}/deploy/webmodbusterm" "\$@"
EOF
chmod +x "${BIN_DST}" "${PREFIX}/deploy/webmodbusterm" "${PREFIX}/deploy/install.sh"

UNIT_SRC="${PREFIX}/deploy/webmodbusterm.service"
sed \
  -e "s|/opt/webmodbusterm|${PREFIX}|g" \
  "${UNIT_SRC}" > "${SERVICE_DST}"

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"

if command -v ro >/dev/null 2>&1; then
  ro || true
fi

echo
echo "WebModbusTerm installed."
echo "  CLI:    webmodbusterm help"
echo "  Open:   http://$(hostname -I 2>/dev/null | awk '{print $1}'):8088  (or http://127.0.0.1:8088)"
echo "  Status: webmodbusterm status"
echo "  Logs:   webmodbusterm logs"
echo "  Stop:   webmodbusterm stop"
