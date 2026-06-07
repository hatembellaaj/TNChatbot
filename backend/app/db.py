import os

import psycopg

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

def get_connection() -> psycopg.Connection:
    conn = psycopg.connect(DATABASE_URL)
    conn.autocommit = True
    return conn
