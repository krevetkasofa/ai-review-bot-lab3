import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from app import inventory


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE stock (sku TEXT PRIMARY KEY, name TEXT, quantity INTEGER)")
    conn.execute("CREATE TABLE stock_archive (sku TEXT)")
    conn.executemany(
        "INSERT INTO stock VALUES (?, ?, ?)",
        [("A-100", "Болт", 50), ("B-200", "Гайка", 20), ("C-300", "Шайба", 5)],
    )
    conn.commit()
    return conn


class InventoryTests(unittest.TestCase):
    def test_list_items_sorted_by_default(self):
        names = [row[1] for row in inventory.list_items(make_conn())]
        self.assertEqual(names, sorted(names))

    def test_count_rows_and_unknown_table(self):
        conn = make_conn()
        self.assertEqual(inventory.count_rows(conn, "stock"), 3)
        with self.assertRaises(ValueError):
            inventory.count_rows(conn, "customers")

    def test_paginate_returns_requested_size(self):
        self.assertEqual(len(inventory.paginate(list(range(10)), 1, 3)), 3)

    def test_count_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "stock.txt")
            with open(path, "w", encoding="utf-8") as stock_file:
                stock_file.write("a\nb\nc\n")
            self.assertEqual(inventory.count_lines(path), 3)

    def test_get_stock(self):
        conn = make_conn()
        self.assertEqual(inventory.get_stock(conn, "A-100"), 50)
        self.assertEqual(inventory.get_stock(conn, "Z-999"), 0)

    def test_reserve_stock(self):
        conn = make_conn()
        self.assertTrue(inventory.reserve_stock(conn, "A-100", 10))
        self.assertEqual(inventory.get_stock(conn, "A-100"), 40)
        self.assertFalse(inventory.reserve_stock(conn, "C-300", 6))

    def test_read_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "daily.txt"), "w", encoding="utf-8") as report_file:
                report_file.write("ok")
            with mock.patch.object(inventory, "REPORTS_DIR", tmp):
                self.assertEqual(inventory.read_report("daily.txt"), "ok")

    def test_cache_key_is_stable(self):
        self.assertEqual(inventory.cache_key("A-100"), inventory.cache_key("A-100"))

    def test_parse_quantity(self):
        self.assertEqual(inventory.parse_quantity("12"), 12)
        self.assertEqual(inventory.parse_quantity("abc"), 0)

    def test_average_stock(self):
        self.assertEqual(inventory.average_stock([]), 0.0)
        self.assertEqual(inventory.average_stock([2, 4]), 3.0)

    def test_collect_skus(self):
        self.assertEqual(inventory.collect_skus([("A",), ("B",), ("A",)]), {"A", "B"})

    def test_lookup_price(self):
        self.assertEqual(inventory.lookup_price("A-100"), 10.0)
        self.assertEqual(inventory.lookup_price("nope", default=1.5), 1.5)


if __name__ == "__main__":
    unittest.main()
