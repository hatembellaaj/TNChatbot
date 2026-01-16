import os

import psycopg

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_connection() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)
