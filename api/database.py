"""
database.py — Conexão com SQL Server via pyodbc (pool simples por thread).

Parâmetros de conexão vêm de settings.py (arquivo .env / variáveis DB_*).
"""

import threading
import pyodbc

from settings import get_database_settings

_local = threading.local()


def get_conn() -> pyodbc.Connection:
    if not getattr(_local, "conn", None):
        _local.conn = pyodbc.connect(get_database_settings().connection_string(), autocommit=True)
    return _local.conn


def close_conn() -> None:
    if getattr(_local, "conn", None):
        _local.conn.close()
        _local.conn = None
