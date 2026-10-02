"""WebModbusTerm - serial / Modbus web terminal."""

from __future__ import annotations

try:
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("webmodbusterm")
except PackageNotFoundError:  # pragma: no cover - editable / source tree
    from pathlib import Path

    __version__ = (Path(__file__).resolve().parents[1] / "VERSION").read_text(
        encoding="utf-8"
    ).strip()
