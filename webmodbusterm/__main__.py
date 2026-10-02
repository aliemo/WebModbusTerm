"""CLI entry: ``webmodbusterm`` / ``python -m webmodbusterm``."""

from __future__ import annotations

import argparse
import os


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="webmodbusterm",
        description="WebModbusTerm - Modbus Monitor and Management Toolchain",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("WEBMODBUSTERM_HOST", "0.0.0.0"),
        help="Bind host (default: 0.0.0.0 or WEBMODBUSTERM_HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("WEBMODBUSTERM_PORT", "8088")),
        help="Bind port (default: 8088 or WEBMODBUSTERM_PORT)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (development)",
    )
    args = parser.parse_args(argv)

    import uvicorn

    uvicorn.run(
        "webmodbusterm.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
