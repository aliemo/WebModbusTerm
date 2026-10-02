"""Load connection profiles and commands.yml for WebModbusTerm."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parent


def _resolve_config_dir() -> Path:
    override = os.environ.get("WEBMODBUSTERM_CONFIG_DIR", "").strip()
    if override:
        return Path(override)
    return PACKAGE_ROOT / "configs"


CONFIG_DIR = _resolve_config_dir()
COMMANDS_FILE = CONFIG_DIR / "commands.yml"


def ensure_config_dir() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not COMMANDS_FILE.exists():
        _dump_yaml(
            COMMANDS_FILE,
            {
                "commands": [
                    {
                        "id": "read_status",
                        "title": "Read Status",
                        "value": "01 03 00 00 00 0A",
                        "encoding": "hex",
                    }
                ]
            },
        )
    return CONFIG_DIR


def list_configs() -> list[dict[str, str]]:
    """List connection YAML profiles (excludes commands.yml)."""
    ensure_config_dir()
    items: list[dict[str, str]] = []
    for path in sorted(CONFIG_DIR.glob("*.yml")) + sorted(CONFIG_DIR.glob("*.yaml")):
        if path.name.lower() in {"commands.yml", "commands.yaml"}:
            continue
        try:
            data = _load_yaml(path)
        except Exception as exc:  # noqa: BLE001
            items.append(
                {
                    "id": path.stem,
                    "file": path.name,
                    "name": path.stem,
                    "description": f"Invalid YAML: {exc}",
                    "error": str(exc),
                }
            )
            continue
        items.append(
            {
                "id": path.stem,
                "file": path.name,
                "name": str(data.get("name") or path.stem),
                "description": str(data.get("description") or ""),
            }
        )
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in items:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        unique.append(item)
    return unique


def get_config(config_id: str) -> dict[str, Any]:
    path = _resolve_config_path(config_id)
    data = _load_yaml(path)
    return _normalize_config(data, config_id=path.stem, filename=path.name)


def get_commands_file() -> dict[str, Any]:
    ensure_config_dir()
    data = _load_yaml(COMMANDS_FILE) if COMMANDS_FILE.exists() else {"commands": []}
    commands = [
        _normalize_command(raw, idx)
        for idx, raw in enumerate(data.get("commands") or [])
        if isinstance(raw, dict)
    ]
    return {"file": COMMANDS_FILE.name, "commands": commands}


def find_command(command_id: str) -> dict[str, Any]:
    for cmd in get_commands_file()["commands"]:
        if cmd.get("id") == command_id or cmd.get("title") == command_id:
            return cmd
    raise KeyError(f"Command not found: {command_id}")


def save_commands(commands: list[dict[str, Any]]) -> dict[str, Any]:
    ensure_config_dir()
    normalized = [_normalize_command(c, idx) for idx, c in enumerate(commands)]
    _dump_yaml(COMMANDS_FILE, {"commands": [_to_yaml_command(c) for c in normalized]})
    return get_commands_file()


def upsert_command(command: dict[str, Any]) -> dict[str, Any]:
    current = get_commands_file()["commands"]
    new_cmd = _normalize_command(command, len(current))
    replaced = False
    for i, existing in enumerate(current):
        if existing.get("id") == new_cmd["id"]:
            current[i] = new_cmd
            replaced = True
            break
    if not replaced:
        current.append(new_cmd)
    return save_commands(current)


def delete_command(command_id: str) -> dict[str, Any]:
    current = get_commands_file()["commands"]
    filtered = [c for c in current if c.get("id") != command_id]
    if len(filtered) == len(current):
        raise KeyError(f"Command not found: {command_id}")
    return save_commands(filtered)


def parse_commands_yaml(text: str) -> list[dict[str, Any]]:
    data = yaml.safe_load(text) or {}
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        raw_list = data.get("commands") or []
    else:
        raise ValueError("YAML must be a mapping with 'commands' or a list of commands")
    if not isinstance(raw_list, list):
        raise ValueError("commands must be a list")
    out = []
    for idx, raw in enumerate(raw_list):
        if isinstance(raw, dict):
            out.append(_normalize_command(raw, idx))
    if not out:
        raise ValueError("No commands found in YAML")
    return out


def parse_commands_csv(text: str) -> list[dict[str, Any]]:
    import csv
    from io import StringIO

    # Strip BOM if present
    if text.startswith("\ufeff"):
        text = text[1:]
    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    fields = { (f or "").strip().lower(): f for f in reader.fieldnames }

    def col(*names: str) -> str | None:
        for n in names:
            if n in fields:
                return fields[n]
        return None

    id_col = col("id", "command_id", "cmd_id")
    title_col = col("title", "name", "command", "label")
    value_col = col("value", "payload", "hex", "data", "command_value")
    if not value_col:
        raise ValueError("CSV needs a value/payload/hex column")

    out: list[dict[str, Any]] = []
    for idx, row in enumerate(reader):
        if not row:
            continue
        value = str(row.get(value_col) or "").strip()
        if not value:
            continue
        title = str(row.get(title_col) or "").strip() if title_col else ""
        cmd_id = str(row.get(id_col) or "").strip() if id_col else ""
        encoding_col = col("encoding", "format", "type")
        ending_col = col("line_ending", "ending", "eol")
        confirm_col = col("confirm", "ask_confirm")
        raw = {
            "id": cmd_id or None,
            "title": title or None,
            "value": value,
            "encoding": (str(row.get(encoding_col) or "hex").strip() if encoding_col else "hex"),
            "line_ending": (str(row.get(ending_col) or "none").strip() if ending_col else "none"),
            "confirm": _csv_bool(row.get(confirm_col)) if confirm_col else False,
        }
        out.append(_normalize_command(raw, idx))
    if not out:
        raise ValueError("No commands found in CSV")
    return out


def _csv_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def import_commands_text(
    text: str,
    *,
    filename: str = "",
    mode: str = "replace",
) -> dict[str, Any]:
    """Import commands from YAML or CSV text into commands.yml."""
    name = (filename or "").lower()
    stripped = text.strip()
    if not stripped:
        raise ValueError("File is empty")

    if name.endswith(".csv"):
        imported = parse_commands_csv(text)
    elif name.endswith((".yml", ".yaml")):
        imported = parse_commands_yaml(text)
    else:
        # Auto-detect by content
        first = stripped.splitlines()[0]
        if first.lstrip().startswith("commands:") or first.lstrip().startswith("-"):
            imported = parse_commands_yaml(text)
        elif "," in first:
            imported = parse_commands_csv(text)
        else:
            try:
                imported = parse_commands_yaml(text)
            except Exception:
                imported = parse_commands_csv(text)

    mode = (mode or "replace").lower().strip()
    if mode == "merge":
        current = {c["id"]: c for c in get_commands_file()["commands"]}
        for cmd in imported:
            current[cmd["id"]] = cmd
        data = save_commands(list(current.values()))
    else:
        data = save_commands(imported)
    data["imported"] = len(imported)
    data["mode"] = mode
    return data


def create_config(
    config_id: str,
    *,
    name: str | None = None,
    description: str = "",
    connection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_config_dir()
    safe = _safe_id(config_id)
    if safe == "commands":
        raise ValueError("Reserved name: commands")
    path = CONFIG_DIR / f"{safe}.yml"
    if path.exists():
        raise FileExistsError(f"Config already exists: {safe}")
    data = {
        "name": name or safe,
        "description": description,
        "connection": connection
        or {
            "mode": "raw",
            "port": "/dev/ttyUSB0",
            "baudrate": 38400,
            "bytesize": 8,
            "parity": "N",
            "stopbits": 1,
            "unit_id": 1,
        },
    }
    _dump_yaml(path, data)
    return get_config(safe)


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    if not safe:
        raise ValueError("Invalid config id")
    return safe


def _resolve_config_path(config_id: str) -> Path:
    ensure_config_dir()
    safe = Path(config_id).name
    if safe.lower() in {"commands", "commands.yml", "commands.yaml"}:
        raise FileNotFoundError("Use /api/commands for commands.yml")
    for ext in (".yml", ".yaml"):
        path = CONFIG_DIR / f"{safe}{ext}"
        if path.exists():
            return path
    direct = CONFIG_DIR / safe
    if direct.exists() and direct.suffix in {".yml", ".yaml"}:
        return direct
    raise FileNotFoundError(f"Config not found: {config_id}")


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError("Config root must be a mapping")
    return data


def _dump_yaml(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)


def _to_yaml_command(cmd: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": cmd["id"],
        "title": cmd.get("title") or cmd.get("name") or cmd["id"],
        "value": cmd.get("value") or "",
    }
    encoding = cmd.get("encoding") or "hex"
    if encoding and encoding != "hex":
        out["encoding"] = encoding
    if cmd.get("line_ending") and cmd.get("line_ending") != "none":
        out["line_ending"] = cmd["line_ending"]
    if cmd.get("confirm"):
        out["confirm"] = True
    if cmd.get("description"):
        out["description"] = cmd["description"]
    # default True for hex commands; persist explicitly when False
    append_crc = bool(cmd.get("append_crc", encoding == "hex"))
    out["append_crc"] = append_crc
    return out


def _normalize_command(raw: dict[str, Any], idx: int) -> dict[str, Any]:
    cmd = dict(raw)
    cmd_id = str(cmd.get("id") or cmd.get("name") or cmd.get("title") or f"cmd_{idx + 1}")
    title = str(cmd.get("title") or cmd.get("name") or cmd_id)
    value = str(cmd.get("value") if cmd.get("value") is not None else cmd.get("payload") or "")
    encoding = str(cmd.get("encoding") or ("hex" if value else "ascii")).lower()
    append_crc = cmd.get("append_crc")
    if append_crc is None:
        append_crc = encoding == "hex"
    return {
        "id": cmd_id,
        "title": title,
        "name": title,
        "value": value,
        "encoding": encoding,
        "line_ending": str(cmd.get("line_ending") or "none"),
        "description": str(cmd.get("description") or ""),
        "confirm": bool(cmd.get("confirm") or False),
        "append_crc": bool(append_crc),
        "action": "raw",
    }


def _normalize_config(data: dict[str, Any], *, config_id: str, filename: str) -> dict[str, Any]:
    connection = dict(data.get("connection") or {})
    connection.setdefault("mode", "raw")
    connection.setdefault("port", "")
    connection.setdefault("baudrate", 9600)
    connection.setdefault("bytesize", 8)
    connection.setdefault("parity", "N")
    connection.setdefault("stopbits", 1)
    connection.setdefault("host", "127.0.0.1")
    connection.setdefault("tcp_port", 502)
    connection.setdefault("unit_id", 1)
    return {
        "id": config_id,
        "file": filename,
        "name": str(data.get("name") or config_id),
        "description": str(data.get("description") or ""),
        "connection": connection,
    }
