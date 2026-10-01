#!/usr/bin/env python3
"""Run WebModbusTerm:  python run.py"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8088,
        reload=False,
    )
