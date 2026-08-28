#!/usr/bin/env python3
"""Rebuild app.py from base64 parts after clone: python rebuild_app.py"""
import base64
from pathlib import Path
parts = sorted(Path(".").glob("app.b64.part*"))
if not parts:
    raise SystemExit("No app.b64.part* files found")
data = "".join(p.read_text().strip() for p in parts)
Path("app.py").write_text(base64.b64decode(data).decode())
print("Wrote app.py", Path("app.py").stat().st_size, "bytes")
