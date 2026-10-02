"""Serial port bridge with optional Modbus RTU framing helpers."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import serial
import serial.tools.list_ports
from pymodbus.client import ModbusSerialClient, ModbusTcpClient

try:
    from pymodbus.framer import FramerType

    _RTU_FRAMER = FramerType.RTU
except Exception:  # noqa: BLE001
    _RTU_FRAMER = "rtu"


LineEnding = str  # "", "\n", "\r", "\r\n"


def list_serial_ports() -> list[dict[str, str]]:
    ports = []
    for p in serial.tools.list_ports.comports():
        ports.append(
            {
                "device": p.device,
                "description": p.description or "",
                "hwid": p.hwid or "",
            }
        )
    return ports


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def bytes_to_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def modbus_crc16(data: bytes) -> int:
    """Modbus RTU CRC-16 (poly 0xA001, init 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def crc_bytes_le(data: bytes) -> bytes:
    """CRC as two bytes, low byte first (Modbus RTU order)."""
    crc = modbus_crc16(data)
    return bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def normalize_crc_mode(mode: str | bool | None) -> str:
    if mode is True or str(mode).lower() in {"on", "true", "1", "modbus", "modbus_crc"}:
        return "modbus"
    if mode is False or mode is None or str(mode).lower() in {"", "off", "none", "n/a", "na", "disabled"}:
        return "none"
    key = str(mode).strip().lower().replace(" ", "")
    aliases = {
        "0x0000": "0x0000",
        "0000": "0x0000",
        "zeros2": "0x0000",
        "0x00": "0x00",
        "00": "0x00",
        "zero": "0x00",
        "0xffff": "0xffff",
        "ffff": "0xffff",
        "0xff": "0xff",
        "ff": "0xff",
        "sum8": "sum8",
        "checksum8": "sum8",
        "xor8": "xor8",
        "modbus": "modbus",
        "none": "none",
    }
    return aliases.get(key, "none")


def compute_crc_tail(body: bytes, mode: str | bool | None) -> bytes:
    """Return trailing CRC/check bytes for the selected mode (may be empty)."""
    m = normalize_crc_mode(mode)
    if m == "none":
        return b""
    if m == "modbus":
        return crc_bytes_le(body)
    if m == "0x0000":
        return b"\x00\x00"
    if m == "0x00":
        return b"\x00"
    if m == "0xffff":
        return b"\xff\xff"
    if m == "0xff":
        return b"\xff"
    if m == "sum8":
        return bytes((sum(body) & 0xFF,))
    if m == "xor8":
        x = 0
        for b in body:
            x ^= b
        return bytes((x & 0xFF,))
    return b""


CRC_MODE_LABELS = {
    "none": "N/A (disabled)",
    "modbus": "MODBUS CRC-16",
    "0x0000": "0x0000",
    "0x00": "0x00",
    "0xffff": "0xFFFF",
    "0xff": "0xFF",
    "sum8": "SUM8",
    "xor8": "XOR8",
}


def parse_hex_payload(text: str) -> bytes:
    cleaned = (
        text.replace("0x", " ")
        .replace("0X", " ")
        .replace(",", " ")
        .replace(":", " ")
        .replace("-", " ")
        .strip()
    )
    if not cleaned:
        return b""
    # Reject non-hex content (aside from whitespace)
    compact = cleaned.replace(" ", "")
    if any(c not in "0123456789abcdefABCDEF" for c in compact):
        raise ValueError("HEX mode only accepts hex digits (0-9, A-F) and spaces")
    parts = cleaned.split()
    out = bytearray()
    for part in parts:
        if len(part) % 2 == 1:
            part = "0" + part
        for i in range(0, len(part), 2):
            out.append(int(part[i : i + 2], 16))
    return bytes(out)


@dataclass
class ConnectionState:
    connected: bool = False
    mode: str = "raw"  # raw | modbus_rtu | modbus_tcp
    port: str = ""
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1
    host: str = "127.0.0.1"
    tcp_port: int = 502
    unit_id: int = 1
    last_error: str = ""


@dataclass
class SerialBridge:
    on_event: Callable[[dict[str, Any]], None]
    state: ConnectionState = field(default_factory=ConnectionState)
    _ser: Optional[serial.Serial] = None
    _reader_thread: Optional[threading.Thread] = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _modbus: Optional[Any] = None
    _loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def emit(self, event: dict[str, Any]) -> None:
        event.setdefault("ts", _utc_ts())
        self.on_event(event)

    def status(self) -> dict[str, Any]:
        return {
            "connected": self.state.connected,
            "mode": self.state.mode,
            "port": self.state.port,
            "baudrate": self.state.baudrate,
            "bytesize": self.state.bytesize,
            "parity": self.state.parity,
            "stopbits": self.state.stopbits,
            "host": self.state.host,
            "tcp_port": self.state.tcp_port,
            "unit_id": self.state.unit_id,
            "last_error": self.state.last_error,
        }

    def connect_raw_or_rtu(
        self,
        *,
        mode: str,
        port: str,
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: float = 1,
        unit_id: int = 1,
    ) -> dict[str, Any]:
        self.disconnect()
        parity_map = {
            "N": serial.PARITY_NONE,
            "E": serial.PARITY_EVEN,
            "O": serial.PARITY_ODD,
            "M": serial.PARITY_MARK,
            "S": serial.PARITY_SPACE,
        }
        stop_map = {
            1: serial.STOPBITS_ONE,
            1.5: serial.STOPBITS_ONE_POINT_FIVE,
            2: serial.STOPBITS_TWO,
        }
        byte_map = {
            5: serial.FIVEBITS,
            6: serial.SIXBITS,
            7: serial.SEVENBITS,
            8: serial.EIGHTBITS,
        }

        try:
            if mode == "modbus_rtu":
                client = ModbusSerialClient(
                    port=port,
                    framer=_RTU_FRAMER,
                    baudrate=baudrate,
                    bytesize=byte_map.get(bytesize, serial.EIGHTBITS),
                    parity=parity_map.get(parity.upper(), serial.PARITY_NONE),
                    stopbits=stop_map.get(stopbits, serial.STOPBITS_ONE),
                    timeout=1.0,
                )
                if not client.connect():
                    raise RuntimeError(f"Failed to open Modbus RTU on {port}")
                self._modbus = client
                # Also open a companion raw reader only in raw mode.
                # For RTU, traffic is driven by explicit Modbus ops.
            else:
                self._ser = serial.Serial(
                    port=port,
                    baudrate=baudrate,
                    bytesize=byte_map.get(bytesize, serial.EIGHTBITS),
                    parity=parity_map.get(parity.upper(), serial.PARITY_NONE),
                    stopbits=stop_map.get(stopbits, serial.STOPBITS_ONE),
                    timeout=0.05,
                )
                self._stop.clear()
                self._reader_thread = threading.Thread(
                    target=self._read_loop, name="serial-reader", daemon=True
                )
                self._reader_thread.start()

            self.state.connected = True
            self.state.mode = mode
            self.state.port = port
            self.state.baudrate = baudrate
            self.state.bytesize = bytesize
            self.state.parity = parity.upper()
            self.state.stopbits = stopbits
            self.state.unit_id = unit_id
            self.state.last_error = ""
            self.emit(
                {
                    "type": "status",
                    "message": f"Connected ({mode}) {port} @ {baudrate}",
                    **self.status(),
                }
            )
            return self.status()
        except Exception as exc:  # noqa: BLE001
            self.state.last_error = str(exc)
            self.emit({"type": "error", "message": str(exc)})
            self.disconnect()
            raise

    def connect_tcp(self, *, host: str, tcp_port: int = 502, unit_id: int = 1) -> dict[str, Any]:
        self.disconnect()
        try:
            client = ModbusTcpClient(host=host, port=tcp_port, timeout=2.0)
            if not client.connect():
                raise RuntimeError(f"Failed to connect Modbus TCP {host}:{tcp_port}")
            self._modbus = client
            self.state.connected = True
            self.state.mode = "modbus_tcp"
            self.state.host = host
            self.state.tcp_port = tcp_port
            self.state.unit_id = unit_id
            self.state.last_error = ""
            self.emit(
                {
                    "type": "status",
                    "message": f"Connected (modbus_tcp) {host}:{tcp_port}",
                    **self.status(),
                }
            )
            return self.status()
        except Exception as exc:  # noqa: BLE001
            self.state.last_error = str(exc)
            self.emit({"type": "error", "message": str(exc)})
            self.disconnect()
            raise

    def disconnect(self) -> dict[str, Any]:
        self._stop.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        self._reader_thread = None

        with self._lock:
            if self._ser and self._ser.is_open:
                try:
                    self._ser.close()
                except Exception:  # noqa: BLE001
                    pass
            self._ser = None

        if self._modbus is not None:
            try:
                self._modbus.close()
            except Exception:  # noqa: BLE001
                pass
            self._modbus = None

        was = self.state.connected
        self.state.connected = False
        if was:
            self.emit({"type": "status", "message": "Disconnected", **self.status()})
        return self.status()

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                with self._lock:
                    ser = self._ser
                    if ser is None or not ser.is_open:
                        break
                    waiting = ser.in_waiting
                    data = ser.read(waiting or 1) if waiting else ser.read(1)
                if data:
                    parts = self._frame_parts(data, detect_crc=True)
                    self.emit(
                        {
                            "type": "rx",
                            "hex": parts["frame_hex"],
                            "ascii": self._safe_ascii(data),
                            "len": len(data),
                            **parts,
                        }
                    )
                else:
                    time.sleep(0.01)
            except Exception as exc:  # noqa: BLE001
                self.state.last_error = str(exc)
                self.emit({"type": "error", "message": f"RX error: {exc}"})
                break
        self.state.connected = False

    @staticmethod
    def _safe_ascii(data: bytes) -> str:
        return "".join(chr(b) if 32 <= b < 127 else "." for b in data)

    @staticmethod
    def _frame_parts(
        data: bytes,
        *,
        crc_mode: str = "none",
        crc_len: int = 0,
        detect_crc: bool = False,
    ) -> dict[str, Any]:
        """Split payload / CRC for display."""
        mode = normalize_crc_mode(crc_mode)
        if crc_len > 0 and len(data) >= crc_len:
            body, crc = data[:-crc_len], data[-crc_len:]
            expected = compute_crc_tail(body, mode) if mode not in {"none"} else b""
            return {
                "payload_hex": bytes_to_hex(body),
                "crc_hex": bytes_to_hex(crc),
                "crc_ok": (crc == expected) if expected else None,
                "crc_mode": mode,
                "frame_hex": bytes_to_hex(data),
            }
        # Auto-detect Modbus CRC only
        if detect_crc and len(data) >= 4:
            body, crc = data[:-2], data[-2:]
            expected = crc_bytes_le(body)
            if crc == expected:
                return {
                    "payload_hex": bytes_to_hex(body),
                    "crc_hex": bytes_to_hex(crc),
                    "crc_ok": True,
                    "crc_mode": "modbus",
                    "frame_hex": bytes_to_hex(data),
                }
        return {
            "payload_hex": bytes_to_hex(data),
            "crc_hex": "",
            "crc_ok": None,
            "crc_mode": mode,
            "frame_hex": bytes_to_hex(data),
        }

    def send_raw(
        self,
        payload: str,
        *,
        encoding: str = "ascii",
        line_ending: LineEnding = "",
        append_crc: bool | None = None,
        crc_mode: str | None = None,
    ) -> dict[str, Any]:
        if encoding == "hex":
            body = parse_hex_payload(payload)
        else:
            body = (payload + line_ending).encode("utf-8", errors="replace")

        # Prefer crc_mode; keep append_crc for backward compatibility
        if crc_mode is None and append_crc is not None:
            mode = "modbus" if append_crc else "none"
        else:
            mode = normalize_crc_mode(crc_mode)
        crc = compute_crc_tail(body, mode)
        data = body + crc

        with self._lock:
            if self._ser is not None and self._ser.is_open:
                written = self._ser.write(data)
                self._ser.flush()
            elif self._modbus is not None and getattr(self._modbus, "socket", None) is not None:
                sock = self._modbus.socket
                written = sock.write(data)
                if hasattr(sock, "flush"):
                    sock.flush()
                time.sleep(0.05)
                try:
                    waiting = getattr(sock, "in_waiting", 0) or 0
                    rx = sock.read(waiting) if waiting and hasattr(sock, "read") else b""
                except Exception:  # noqa: BLE001
                    rx = b""
                if rx:
                    parts = self._frame_parts(rx, detect_crc=True)
                    self.emit(
                        {
                            "type": "rx",
                            "hex": parts["frame_hex"],
                            "ascii": self._safe_ascii(rx),
                            "len": len(rx),
                            **parts,
                        }
                    )
            else:
                raise RuntimeError("Serial is not connected (use raw or modbus_rtu)")

        parts = self._frame_parts(data, crc_mode=mode, crc_len=len(crc))
        info = {
            "type": "tx",
            "hex": parts["frame_hex"],
            "ascii": self._safe_ascii(data),
            "len": written,
            "append_crc": mode != "none",
            "crc_mode": mode,
            **parts,
        }
        self.emit(info)
        return info

    def modbus_request(
        self,
        *,
        function: str,
        address: int,
        quantity: int = 1,
        values: Optional[list[int | bool]] = None,
        unit_id: Optional[int] = None,
    ) -> dict[str, Any]:
        if self._modbus is None or not self.state.connected:
            raise RuntimeError("Modbus client is not connected")

        slave = unit_id if unit_id is not None else self.state.unit_id
        client = self._modbus
        values = values or []
        fn = function.lower().strip()

        # pymodbus 3.x uses device_id / slave keyword depending on version.
        kwargs: dict[str, Any] = {"device_id": slave}

        try:
            if fn in ("01", "read_coils"):
                rr = client.read_coils(address, count=quantity, **kwargs)
                payload = list(rr.bits[:quantity]) if not rr.isError() else None
            elif fn in ("02", "read_discrete_inputs"):
                rr = client.read_discrete_inputs(address, count=quantity, **kwargs)
                payload = list(rr.bits[:quantity]) if not rr.isError() else None
            elif fn in ("03", "read_holding_registers"):
                rr = client.read_holding_registers(address, count=quantity, **kwargs)
                payload = list(rr.registers) if not rr.isError() else None
            elif fn in ("04", "read_input_registers"):
                rr = client.read_input_registers(address, count=quantity, **kwargs)
                payload = list(rr.registers) if not rr.isError() else None
            elif fn in ("05", "write_coil"):
                val = bool(values[0]) if values else False
                rr = client.write_coil(address, val, **kwargs)
                payload = [val]
            elif fn in ("06", "write_register"):
                val = int(values[0]) if values else 0
                rr = client.write_register(address, val, **kwargs)
                payload = [val]
            elif fn in ("15", "write_coils"):
                bits = [bool(v) for v in values]
                rr = client.write_coils(address, bits, **kwargs)
                payload = bits
            elif fn in ("16", "write_registers"):
                regs = [int(v) & 0xFFFF for v in values]
                rr = client.write_registers(address, regs, **kwargs)
                payload = regs
            else:
                raise ValueError(f"Unsupported function: {function}")

            if rr.isError():
                raise RuntimeError(str(rr))

            result = {
                "type": "modbus",
                "ok": True,
                "function": fn,
                "address": address,
                "quantity": quantity,
                "unit_id": slave,
                "values": payload,
            }
            self.emit(result)
            return result
        except TypeError:
            # Fallback for older pymodbus keyword `slave=`
            kwargs = {"slave": slave}
            return self._modbus_request_legacy(
                function=fn,
                address=address,
                quantity=quantity,
                values=values,
                kwargs=kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            err = {
                "type": "modbus",
                "ok": False,
                "function": fn,
                "address": address,
                "quantity": quantity,
                "unit_id": slave,
                "error": str(exc),
            }
            self.emit(err)
            raise

    def _modbus_request_legacy(
        self,
        *,
        function: str,
        address: int,
        quantity: int,
        values: list[int | bool],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        client = self._modbus
        fn = function
        if fn in ("01", "read_coils"):
            rr = client.read_coils(address, count=quantity, **kwargs)
            payload = list(rr.bits[:quantity]) if not rr.isError() else None
        elif fn in ("02", "read_discrete_inputs"):
            rr = client.read_discrete_inputs(address, count=quantity, **kwargs)
            payload = list(rr.bits[:quantity]) if not rr.isError() else None
        elif fn in ("03", "read_holding_registers"):
            rr = client.read_holding_registers(address, count=quantity, **kwargs)
            payload = list(rr.registers) if not rr.isError() else None
        elif fn in ("04", "read_input_registers"):
            rr = client.read_input_registers(address, count=quantity, **kwargs)
            payload = list(rr.registers) if not rr.isError() else None
        elif fn in ("05", "write_coil"):
            val = bool(values[0]) if values else False
            rr = client.write_coil(address, val, **kwargs)
            payload = [val]
        elif fn in ("06", "write_register"):
            val = int(values[0]) if values else 0
            rr = client.write_register(address, val, **kwargs)
            payload = [val]
        elif fn in ("15", "write_coils"):
            bits = [bool(v) for v in values]
            rr = client.write_coils(address, bits, **kwargs)
            payload = bits
        elif fn in ("16", "write_registers"):
            regs = [int(v) & 0xFFFF for v in values]
            rr = client.write_registers(address, regs, **kwargs)
            payload = regs
        else:
            raise ValueError(f"Unsupported function: {function}")

        if rr.isError():
            raise RuntimeError(str(rr))

        result = {
            "type": "modbus",
            "ok": True,
            "function": fn,
            "address": address,
            "quantity": quantity,
            "unit_id": kwargs.get("slave") or kwargs.get("device_id"),
            "values": payload,
        }
        self.emit(result)
        return result
