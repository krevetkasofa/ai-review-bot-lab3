"""Подключение к SQLite и создание таблиц."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    total REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'new'
);
"""


def get_connection(path=":memory:"):
    """Открывает соединение с базой данных."""
    return sqlite3.connect(path)


def init_db(conn):
    """Создаёт таблицы, если их ещё нет."""
    conn.executescript(SCHEMA)
    conn.commit()
