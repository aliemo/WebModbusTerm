"""WebModbusTerm - serial / Modbus web terminal."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.config_loader import (
    COMMANDS_FILE,
    create_config,
    delete_command,
    ensure_config_dir,
    find_command,
    get_commands_file,
    get_config,
    import_commands_text,
    list_configs,
    save_commands,
    upsert_command,
)
from app.serial_bridge import (
    SerialBridge,
    bytes_to_hex,
    compute_crc_tail,
    list_serial_ports,
    normalize_crc_mode,
    parse_hex_payload,
)

ROOT = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))

app = FastAPI(title="WebModbusTerm", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.middleware("http")
async def standalone_security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Keep the UI self-hosted: no CDN / third-party origins."""
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self'; "
        "script-src 'self'; "
        "font-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


_clients: set[WebSocket] = set()
_bridge: SerialBridge | None = None
_main_loop: asyncio.AbstractEventLoop | None = None
_active_config_id: str | None = None


def broadcast_sync(event: dict[str, Any]) -> None:
    from datetime import datetime, timezone

    if "ts" not in event:
        event["ts"] = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
    loop = _main_loop
    if loop is None or not loop.is_running():
        return
    asyncio.run_coroutine_threadsafe(_broadcast(event), loop)


async def _broadcast(event: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    payload = json.dumps(event)
    for ws in list(_clients):
        try:
            await ws.send_text(payload)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)


def get_bridge() -> SerialBridge:
    global _bridge
    if _bridge is None:
        _bridge = SerialBridge(on_event=broadcast_sync)
        if _main_loop is not None:
            _bridge.set_loop(_main_loop)
    return _bridge


@app.on_event("startup")
async def on_startup() -> None:
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    get_bridge().set_loop(_main_loop)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    get_bridge().disconnect()


class ConnectBody(BaseModel):
    mode: str = Field(description="raw | modbus_rtu | modbus_tcp")
    port: str = ""
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1
    host: str = "127.0.0.1"
    tcp_port: int = 502
    unit_id: int = 1


class SendBody(BaseModel):
    payload: str
    encoding: str = "ascii"
    line_ending: str = ""
    append_crc: bool | None = None
    crc_mode: str = "modbus"


class ModbusBody(BaseModel):
    function: str
    address: int
    quantity: int = 1
    values: list[int | bool] = Field(default_factory=list)
    unit_id: int | None = None


class RunCommandBody(BaseModel):
    command_id: str
    confirmed: bool = False
    append_crc: bool | None = None
    crc_mode: str | None = None


class CommandItem(BaseModel):
    id: str
    title: str
    value: str = ""
    encoding: str = "hex"
    line_ending: str = "none"
    description: str = ""
    confirm: bool = False
    append_crc: bool = True
    crc_mode: str | None = None


class CommandsReplaceBody(BaseModel):
    commands: list[CommandItem]


class CreateConfigBody(BaseModel):
    id: str
    name: str | None = None
    description: str = ""
    connection: dict[str, Any] | None = None


def _connect_from_dict(body: dict[str, Any]) -> dict[str, Any]:
    bridge = get_bridge()
    mode = str(body.get("mode", "raw")).lower().strip()
    if mode == "modbus_tcp":
        return bridge.connect_tcp(
            host=str(body.get("host") or "127.0.0.1"),
            tcp_port=int(body.get("tcp_port") or 502),
            unit_id=int(body.get("unit_id") or 1),
        )
    if mode in ("raw", "modbus_rtu"):
        port = str(body.get("port") or "")
        if not port:
            raise HTTPException(status_code=400, detail="Serial port is required")
        return bridge.connect_raw_or_rtu(
            mode=mode,
            port=port,
            baudrate=int(body.get("baudrate") or 9600),
            bytesize=int(body.get("bytesize") or 8),
            parity=str(body.get("parity") or "N"),
            stopbits=float(body.get("stopbits") or 1),
            unit_id=int(body.get("unit_id") or 1),
        )
    raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")


def _run_predefined(
    command_id: str,
    *,
    confirmed: bool,
    append_crc: bool | None = None,
    crc_mode: str | None = None,
) -> dict[str, Any]:
    cmd = find_command(command_id)
    label = cmd.get("title") or cmd.get("id")
    if cmd.get("confirm") and not confirmed:
        raise HTTPException(status_code=400, detail=f"Command '{label}' requires confirmation")

    ending_map = {"none": "", "": "", "lf": "\n", "cr": "\r", "crlf": "\r\n"}
    ending = ending_map.get(str(cmd.get("line_ending") or "none"), "")
    mode = crc_mode
    if mode is None and append_crc is not None:
        mode = "modbus" if append_crc else "none"
    if mode is None:
        mode = "modbus"
    result = get_bridge().send_raw(
        str(cmd.get("value") or ""),
        encoding=str(cmd.get("encoding") or "hex"),
        line_ending=ending,
        crc_mode=mode,
    )
    out = {"command_id": cmd.get("id"), "title": label, "result": result}
    broadcast_sync({"type": "command", "ok": True, "name": label, **out})
    return out


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/ports")
async def api_ports() -> dict[str, Any]:
    return {"ports": list_serial_ports()}


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    return {**get_bridge().status(), "active_config_id": _active_config_id}


@app.get("/api/configs")
async def api_configs() -> dict[str, Any]:
    return {"configs": list_configs(), "active_config_id": _active_config_id}


@app.get("/api/configs/{config_id}")
async def api_config_get(config_id: str) -> dict[str, Any]:
    try:
        return get_config(config_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/configs/{config_id}/load")
async def api_config_load(config_id: str) -> dict[str, Any]:
    """Load connection YAML into the client (settings only - no auto-connect)."""
    global _active_config_id
    try:
        cfg = get_config(config_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _active_config_id = cfg["id"]
    broadcast_sync({"type": "config", "message": f"Loaded YAML: {cfg['name']}", "config_id": cfg["id"]})
    return {"config": cfg, "active_config_id": _active_config_id}


@app.post("/api/configs")
async def api_configs_create(body: CreateConfigBody) -> dict[str, Any]:
    try:
        return create_config(
            body.id,
            name=body.name,
            description=body.description,
            connection=body.connection,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/commands")
async def api_commands_get() -> dict[str, Any]:
    return get_commands_file()


@app.put("/api/commands")
async def api_commands_replace(body: CommandsReplaceBody) -> dict[str, Any]:
    try:
        data = save_commands([c.model_dump() for c in body.commands])
        broadcast_sync({"type": "config", "message": "Saved commands.yml"})
        return data
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/commands")
async def api_commands_upsert(body: CommandItem) -> dict[str, Any]:
    try:
        data = upsert_command(body.model_dump())
        broadcast_sync({"type": "config", "message": f"Saved command: {body.title}"})
        return data
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/commands/{command_id}")
async def api_commands_delete(command_id: str) -> dict[str, Any]:
    try:
        data = delete_command(command_id)
        broadcast_sync({"type": "config", "message": f"Deleted command: {command_id}"})
        return data
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/commands/import")
async def api_commands_import(
    file: UploadFile = File(...),
    mode: str = Form("replace"),
) -> dict[str, Any]:
    try:
        raw = await file.read()
        text = raw.decode("utf-8-sig")
        data = import_commands_text(text, filename=file.filename or "", mode=mode)
        broadcast_sync(
            {
                "type": "config",
                "message": f"Imported {data.get('imported', 0)} commands ({data.get('mode')}) from {file.filename}",
            }
        )
        return data
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/commands/download")
async def api_commands_download() -> FileResponse:
    ensure_config_dir()
    if not COMMANDS_FILE.exists():
        raise HTTPException(status_code=404, detail="commands.yml not found")
    return FileResponse(
        path=COMMANDS_FILE,
        media_type="application/x-yaml",
        filename="commands.yml",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/commands/run")
async def api_commands_run(body: RunCommandBody) -> dict[str, Any]:
    try:
        return _run_predefined(
            body.command_id,
            confirmed=body.confirmed,
            append_crc=body.append_crc,
            crc_mode=body.crc_mode,
        )
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/crc")
async def api_crc(payload: str = "", encoding: str = "hex", crc_mode: str = "modbus") -> dict[str, Any]:
    """Preview CRC/check bytes for a payload (without sending)."""
    try:
        if encoding == "hex":
            body = parse_hex_payload(payload)
        else:
            body = payload.encode("utf-8", errors="replace")
        mode = normalize_crc_mode(crc_mode)
        crc = compute_crc_tail(body, mode)
        frame = body + crc
        return {
            "payload_hex": bytes_to_hex(body),
            "crc_hex": bytes_to_hex(crc),
            "frame_hex": bytes_to_hex(frame),
            "crc_mode": mode,
            "len": len(frame),
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/connect")
async def api_connect(body: ConnectBody) -> dict[str, Any]:
    try:
        return _connect_from_dict(body.model_dump())
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/disconnect")
async def api_disconnect() -> dict[str, Any]:
    return get_bridge().disconnect()


@app.post("/api/send")
async def api_send(body: SendBody) -> dict[str, Any]:
    ending_map = {
        "none": "",
        "": "",
        "lf": "\n",
        "cr": "\r",
        "crlf": "\r\n",
        "\\n": "\n",
        "\\r": "\r",
        "\\r\\n": "\r\n",
    }
    ending = ending_map.get(body.line_ending, body.line_ending)
    try:
        return get_bridge().send_raw(
            body.payload,
            encoding=body.encoding,
            line_ending=ending,
            append_crc=body.append_crc,
            crc_mode=body.crc_mode,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/modbus")
async def api_modbus(body: ModbusBody) -> dict[str, Any]:
    try:
        return get_bridge().modbus_request(
            function=body.function,
            address=body.address,
            quantity=body.quantity,
            values=body.values,
            unit_id=body.unit_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    from datetime import datetime, timezone

    await websocket.accept()
    _clients.add(websocket)
    await websocket.send_text(
        json.dumps(
            {
                "type": "hello",
                "message": "status",
                "ts": datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3],
                **get_bridge().status(),
                "active_config_id": _active_config_id,
            }
        )
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)
