#!/bin/sh
set -e
if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload || true
  systemctl enable webmodbusterm.service || true
  systemctl restart webmodbusterm.service || systemctl start webmodbusterm.service || true
fi
echo "WebModbusTerm installed. Open http://127.0.0.1:8088"
