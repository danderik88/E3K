#!/usr/bin/env python3
"""Copia consistente del DB Spoolman nel repo config (chiamato da autocommit.sh)."""
import sqlite3, os
src_path = os.path.expanduser("~/.local/share/spoolman/spoolman.db")
dst_dir = os.path.expanduser("~/printer_data/config/spoolman_backup")
if os.path.isfile(src_path):
    os.makedirs(dst_dir, exist_ok=True)
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(os.path.join(dst_dir, "spoolman.db"))
    src.backup(dst)
    dst.close(); src.close()
