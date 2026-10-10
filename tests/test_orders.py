import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from app import orders
from app.auth import register_user
from app.customers import create_customer, get_customer
from app.db import get_connection, init_db


class OrdersTest(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection()
        init_db(self.conn)
        self.customer_id = create_customer(self.conn, "Анна", "anna@example.com", "secret")
        self.conn.execute(
            "INSERT INTO orders (customer_id, total, status) VALUES (?, ?, 'new')",
            (self.customer_id, 100.0),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_calc_total(self):
        self.assertEqual(orders.CalcTotal([10, 20, 30]), 60)

    def test_apply_discount(self):
        self.assertEqual(orders.apply_discount(100.0, 5), 100.0)
        self.assertEqual(orders.apply_discount(100.0, 20), 90.0)

    def test_add_item(self):
        order = {"items": []}
        tags = orders.add_item(order, {"name": "чай"}, tags=[])
        self.assertEqual(order["items"], [{"name": "чай"}])
        self.assertEqual(tags, ["чай"])

    def test_average_order_value(self):
        self.assertEqual(orders.average_order_value([10, 20]), 15)

    def test_find_orders_by_customer(self):
        self.assertEqual(orders.find_orders_by_customer(self.conn, "Анна"), [(1, 100.0)])

    def test_get_orders_by_ids(self):
        self.assertEqual(orders.get_orders_by_ids(self.conn, [1]), [(1, 100.0, "new")])

    def test_get_shipping_quote(self):
        fake_response = mock.Mock()
        fake_response.read.return_value = b'{"price": 250}'
        with mock.patch("urllib.request.urlopen", return_value=fake_response):
            self.assertEqual(orders.get_shipping_quote(2), {"price": 250})

    def test_save_order_log(self):
        with tempfile.TemporaryDirectory() as folder:
            previous = os.getcwd()
            os.chdir(folder)
            try:
                orders.save_order_log(1, "создан")
                with open("orders.log", encoding="utf-8") as log_file:
                    self.assertEqual(log_file.read(), "1: создан\n")
            finally:
                os.chdir(previous)

    def test_debug_dump(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            orders.debug_dump({"id": 1})
        self.assertEqual(output.getvalue(), "order: {'id': 1}\n")

    def test_pick_promo_banner(self):
        self.assertIn(orders.pick_promo_banner(["a", "b"]), ["a", "b"])

    def test_current_git_revision(self):
        completed = mock.Mock(stdout="abc123\n")
        with mock.patch("subprocess.run", return_value=completed):
            self.assertEqual(orders.current_git_revision(), "abc123")

    def test_load_orders_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "orders.json")
            with open(path, "w", encoding="utf-8") as orders_file:
                json.dump([{"id": 1}], orders_file)
            self.assertEqual(orders.load_orders_file(path), [{"id": 1}])

    def test_register_user(self):
        user_id = register_user(self.conn, "Борис", "boris@example.com", "secret")
        self.assertEqual(get_customer(self.conn, user_id)["name"], "Борис")


if __name__ == "__main__":
    unittest.main()
