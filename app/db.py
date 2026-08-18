"""Conexao com o Postgres local (docker-compose)."""
from __future__ import annotations

import os

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://realce:realce@localhost:5432/realce"
)


def get_connection() -> psycopg.Connection:
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)
    register_vector(conn)
    return conn
