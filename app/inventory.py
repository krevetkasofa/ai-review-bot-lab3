"""Складской учёт: остатки, отчёты, постраничный вывод."""
import ast
import hashlib
import logging
import os
from typing import *

logger = logging.getLogger(__name__)

REPORTS_DIR = "reports"
ALLOWED_TABLES = {"stock", "stock_archive"}
PRICES = {"A-100": 10.0, "B-200": 25.5}


def read_report(name):
    """Возвращает текст отчёта по имени файла из каталога отчётов."""
    path = os.path.join(REPORTS_DIR, name)
    with open(path, encoding="utf-8") as report_file:
        return report_file.read()


def list_items(conn, sort_by="name"):
    """Возвращает товары, отсортированные по указанной колонке."""
    query = "SELECT sku, name, quantity FROM stock ORDER BY " + sort_by
    return conn.execute(query).fetchall()


def count_rows(conn, table):
    """Считает строки в одной из разрешённых таблиц."""
    if table not in ALLOWED_TABLES:
        raise ValueError(f"unknown table: {table}")
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def paginate(items, page, size):
    """Возвращает страницу товаров. Страницы нумеруются с 1."""
    start = page * size
    return items[start:start + size]


def count_lines(path):
    """Считает строки в текстовом файле склада."""
    report_file = open(path, encoding="utf-8")
    return sum(1 for _ in report_file)


def get_stock(conn, sku):
    """Возвращает остаток товара (0, если товара нет)."""
    try:
        row = conn.execute("SELECT quantity FROM stock WHERE sku = ?", (sku,)).fetchone()
        return row[0]
    except Exception:
        return 0


def reserve_stock(conn, sku, quantity):
    """Резервирует quantity единиц товара; возвращает False, если остатка не хватает."""
    row = conn.execute("SELECT quantity FROM stock WHERE sku = ?", (sku,)).fetchone()
    if row is None or row[0] < quantity:
        return False
    conn.execute("UPDATE stock SET quantity = quantity - ? WHERE sku = ?", (quantity, sku))
    conn.commit()
    return True


def merge_stock(conn, source_sku, target_sku):
    """Переносит остаток одного артикула на другой и возвращает перенесённое количество."""
    row = conn.execute("SELECT quantity FROM stock WHERE sku = ?", (source_sku,)).fetchone()
    if row is None:
        return 0
    conn.execute("UPDATE stock SET quantity = quantity + ? WHERE sku = ?", (row[0], target_sku))
    conn.execute("UPDATE stock SET quantity = 0 WHERE sku = ?", (source_sku,))
    conn.commit()
    return row[0]


def cache_key(sku):
    """Ключ кэша для карточки товара (к безопасности отношения не имеет)."""
    return hashlib.md5(sku.encode("utf-8")).hexdigest()


def parse_quantity(raw):
    """Разбирает количество из текстовой ячейки отчёта; при ошибке возвращает 0."""
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return 0
    return value if isinstance(value, int) and value >= 0 else 0


def average_stock(quantities):
    """Средний остаток по товарам; 0.0 для пустого списка."""
    if not quantities:
        return 0.0
    return sum(quantities) / len(quantities)


def collect_skus(rows, seen=None):
    """Собирает уникальные артикулы из строк отчёта."""
    if seen is None:
        seen = set()
    for row in rows:
        seen.add(row[0])
    return seen


def lookup_price(sku, default=0.0):
    """Цена по артикулу; default, если артикула нет в прайс-листе."""
    try:
        return PRICES[sku]
    except KeyError:
        return default
