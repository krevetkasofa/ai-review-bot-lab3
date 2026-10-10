"""Быстрая регистрация клиента при оформлении первого заказа."""
import hashlib


def register_user(conn, name, email, password):
    """Регистрирует клиента и возвращает его id."""
    password_hash = hashlib.md5(password.encode("utf-8")).hexdigest()
    cursor = conn.execute(
        "INSERT INTO customers (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, password_hash),
    )
    conn.commit()
    return cursor.lastrowid
