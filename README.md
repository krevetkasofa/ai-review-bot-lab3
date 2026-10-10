# Магазин: клиенты и заказы

Небольшой учебный проект на Python: учёт клиентов и заказов магазина в базе SQLite. Приложение маленькое и без внешних зависимостей: всё построено на стандартной библиотеке.

## Что умеет

* регистрировать клиентов (имя, email, пароль);
* получать клиента по id;
* хранить пароли безопасно: хешируются через `scrypt` с индивидуальной солью, в базе лежит только «соль:хеш»;
* хранить заказы клиентов (сумма и статус) в таблице `orders`.

Работа с заказами (создание, поиск, отмена и другое) развивается отдельными изменениями через pull request'ы.

## Структура

```
app/
  db.py              подключение к SQLite и схема таблиц
  customers.py       создание и получение клиентов, хеширование паролей
tests/
  test_customers.py  тесты
```

## Модель данных

| Таблица | Поля |
|---|---|
| `customers` | `id`, `name`, `email` (уникальный), `password_hash` |
| `orders` | `id`, `customer_id` (ссылка на `customers`), `total`, `status` (по умолчанию `new`) |

## Быстрый старт

```python
from app.db import get_connection, init_db
from app.customers import create_customer, get_customer

conn = get_connection()          # база в памяти; для файла: get_connection("shop.db")
init_db(conn)                    # создаёт таблицы

customer_id = create_customer(conn, "Анна", "anna@example.com", "secret")
print(get_customer(conn, customer_id))
# {'id': 1, 'name': 'Анна', 'email': 'anna@example.com'}
```

## Тесты

```
python -m unittest discover -s tests -t .
```


