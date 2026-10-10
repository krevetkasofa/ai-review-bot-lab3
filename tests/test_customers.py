import unittest

from app.customers import create_customer, get_customer, hash_password
from app.db import get_connection, init_db


class CustomersTest(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection()
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_create_and_get_customer(self):
        customer_id = create_customer(self.conn, "Анна", "anna@example.com", "secret")
        self.assertEqual(
            get_customer(self.conn, customer_id),
            {"id": customer_id, "name": "Анна", "email": "anna@example.com"},
        )

    def test_get_missing_customer_returns_none(self):
        self.assertIsNone(get_customer(self.conn, 999))

    def test_password_hash_is_salted(self):
        self.assertNotEqual(hash_password("secret"), hash_password("secret"))

    def test_password_hash_is_reproducible_with_same_salt(self):
        salt = b"0123456789abcdef"
        self.assertEqual(hash_password("secret", salt), hash_password("secret", salt))


if __name__ == "__main__":
    unittest.main()
