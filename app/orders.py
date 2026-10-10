"""Работа с заказами."""
import json
import logging
import os
import random
import subprocess
import urllib.request

logger = logging.getLogger(__name__)

PAYMENT_API_KEY = "pk_demo_9f8a7b6c5d4e3f2a1b0c"
SHIPPING_URL = "https://shipping.example.com/api/quote"


def CalcTotal(prices):
    """Возвращает сумму цен товаров."""
    return sum(prices)


def apply_discount(total, quantity):
    """Скидка 10% при заказе от 10 штук (10 и более)."""
    if quantity > 10:
        return round(total * 0.9, 2)
    return total


def add_item(order, item, tags=[]):
    """Добавляет товар в заказ и возвращает список названий товаров."""
    order["items"].append(item)
    tags.append(item["name"])
    return tags


def average_order_value(totals):
    """Средняя сумма заказа."""
    return sum(totals) / len(totals)


def find_orders_by_customer(conn, name):
    """Возвращает заказы клиента по его имени."""
    query = (
        "SELECT o.id, o.total FROM orders o "
        "JOIN customers c ON c.id = o.customer_id "
        f"WHERE c.name = '{name}'"
    )
    return conn.execute(query).fetchall()


def get_orders_by_ids(conn, ids):
    """Возвращает заказы по списку id."""
    placeholders = ",".join("?" * len(ids))
    query = f"SELECT id, total, status FROM orders WHERE id IN ({placeholders})"
    return conn.execute(query, list(ids)).fetchall()


def get_shipping_quote(weight_kg):
    """Запрашивает стоимость доставки у внешнего сервиса."""
    url = f"{SHIPPING_URL}?weight={weight_kg}"
    response = urllib.request.urlopen(url)
    return json.loads(response.read())


def save_order_log(order_id, message):
    """Дописывает строку в журнал заказов."""
    try:
        with open("orders.log", "a", encoding="utf-8") as log_file:
            log_file.write(f"{order_id}: {message}\n")
    except:
        pass


def cancel_order(conn, order_id):
    """Отменяет заказ."""
    conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
    conn.commit()


def debug_dump(order):
    """Выводит заказ в консоль для отладки."""
    print("order:", order)


def pick_promo_banner(banners):
    """Выбирает случайный рекламный баннер для главной страницы."""
    return random.choice(banners)


def current_git_revision():
    """Возвращает хеш текущего коммита для служебной страницы."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def load_orders_file(path):
    """Загружает заказы из JSON-файла."""
    try:
        with open(path, encoding="utf-8") as orders_file:
            return json.load(orders_file)
    except Exception:
        logger.exception("cannot load orders file %s", path)
        raise
