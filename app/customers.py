"""Клиенты магазина."""
import hashlib
import os


def hash_password(password, salt=None):
    """Возвращает строку «соль:хеш», пароль хешируется через scrypt."""
    salt = salt if salt is not None else os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return salt.hex() + ":" + digest.hex()


def create_customer(conn, name, email, password):
    """Создаёт клиента и возвращает его id."""
    cursor = conn.execute(
        "INSERT INTO customers (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, hash_password(password)),
    )
    conn.commit()
    return cursor.lastrowid


def get_customer(conn, customer_id):
    """Возвращает клиента как словарь или None, если такого нет."""
    row = conn.execute(
        "SELECT id, name, email FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "name": row[1], "email": row[2]}
