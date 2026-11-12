from collections import defaultdict
from decimal import Decimal, InvalidOperation

from ..db import execute, fetch_all, fetch_one
from ..utils.time import now


ORDER_STATUSES = ("PENDING", "DELIVERED", "CANCELLED")


class POSValidationError(ValueError):
    pass


class POSNotFound(POSValidationError):
    pass


def _validate_product_values(name, price, stock_qty):
    if not str(name).strip():
        raise POSValidationError("Product name is required.")
    try:
        normalized_price = Decimal(str(price))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise POSValidationError("Enter a valid non-negative price.") from error
    if normalized_price < 0:
        raise POSValidationError("Enter a valid non-negative price.")
    try:
        normalized_stock = int(stock_qty)
    except (TypeError, ValueError) as error:
        raise POSValidationError("Enter a non-negative whole number.") from error
    if normalized_stock < 0:
        raise POSValidationError("Enter a non-negative whole number.")
    return str(name).strip(), normalized_price, normalized_stock


def _transaction(operation):
    from ..db import get_connection

    connection = get_connection()
    try:
        with connection.cursor(dictionary=True) as cursor:
            result = operation(cursor)
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_products(include_inactive=False):
    where = "" if include_inactive else "WHERE is_active = 1"
    return fetch_all(
        f"""
        SELECT id, name, price, stock_qty, is_active
        FROM products
        {where}
        ORDER BY is_active DESC, name
        """
    )


def get_product(product_id):
    return fetch_one(
        "SELECT id, name, price, stock_qty, is_active FROM products WHERE id = %s",
        (product_id,),
    )


def create_product(name, price, stock_qty):
    name, price, stock_qty = _validate_product_values(name, price, stock_qty)
    return execute(
        """
        INSERT INTO products (name, price, stock_qty, is_active)
        VALUES (%s, %s, %s, 1)
        """,
        (name, price, stock_qty),
    )


def update_product(product_id, name, price, stock_qty, is_active):
    name, price, stock_qty = _validate_product_values(name, price, stock_qty)
    return execute(
        """
        UPDATE products
        SET name = %s, price = %s, stock_qty = %s, is_active = %s
        WHERE id = %s
        """,
        (name, price, stock_qty, is_active, product_id),
    )


def get_customer_active_sessions(user_id):
    return fetch_all(
        """
        SELECT s.id, s.customer_name, s.started_at, s.scheduled_end,
               u.name AS unit_name
        FROM sessions s
        INNER JOIN units u ON u.id = s.unit_id
        WHERE s.user_id = %s AND s.status = 'ACTIVE'
        ORDER BY s.started_at DESC
        """,
        (user_id,),
    )


def _parse_items(items):
    quantities = defaultdict(int)
    for product_id, quantity in items:
        try:
            product_id = int(product_id)
            quantity = int(quantity)
        except (TypeError, ValueError) as error:
            raise POSValidationError("Select valid product quantities.") from error
        if product_id <= 0 or quantity <= 0:
            raise POSValidationError("Product quantities must be greater than zero.")
        quantities[product_id] += quantity
    if not quantities:
        raise POSValidationError("Add at least one product to your order.")
    return quantities


def create_order(user_id, session_id, items):
    quantities = _parse_items(items)

    def operation(cursor):
        cursor.execute(
            """
            SELECT id
            FROM sessions
            WHERE id = %s AND user_id = %s AND status = 'ACTIVE'
            FOR UPDATE
            """,
            (session_id, user_id),
        )
        if cursor.fetchone() is None:
            raise POSValidationError("Select one of your active sessions.")

        products = {}
        for product_id in quantities:
            cursor.execute(
                """
                SELECT id, name, price, stock_qty, is_active
                FROM products
                WHERE id = %s
                FOR UPDATE
                """,
                (product_id,),
            )
            product = cursor.fetchone()
            if product is None or not product["is_active"]:
                raise POSValidationError("One of the selected products is unavailable.")
            if product["stock_qty"] < quantities[product_id]:
                raise POSValidationError(
                    f"Insufficient stock for {product['name']}."
                )
            products[product_id] = product

        cursor.execute(
            """
            INSERT INTO orders (session_id, ordered_by, status, created_at)
            VALUES (%s, %s, 'PENDING', %s)
            """,
            (session_id, user_id, now()),
        )
        order_id = cursor.lastrowid
        for product_id, quantity in quantities.items():
            product = products[product_id]
            cursor.execute(
                """
                INSERT INTO order_items (order_id, product_id, quantity, unit_price)
                VALUES (%s, %s, %s, %s)
                """,
                (order_id, product_id, quantity, product["price"]),
            )
            cursor.execute(
                """
                UPDATE products
                SET stock_qty = stock_qty - %s
                WHERE id = %s AND stock_qty >= %s
                """,
                (quantity, product_id, quantity),
            )
            if cursor.rowcount != 1:
                raise POSValidationError("Stock changed before the order was saved.")
        return order_id

    return _transaction(operation)


def _order_query(where):
    return f"""
        SELECT o.id, o.session_id, o.ordered_by, o.status, o.created_at,
               u.name AS unit_name,
               COALESCE(NULLIF(CONCAT_WS(' ', usr.first_name, usr.last_name), ''), 'Walk-in') AS customer_name,
               COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS total,
               GROUP_CONCAT(CONCAT(p.name, ' × ', oi.quantity)
                            ORDER BY p.name SEPARATOR ', ') AS item_summary
        FROM orders o
        INNER JOIN sessions s ON s.id = o.session_id
        INNER JOIN units u ON u.id = s.unit_id
        LEFT JOIN users usr ON usr.id = o.ordered_by
        INNER JOIN order_items oi ON oi.order_id = o.id
        INNER JOIN products p ON p.id = oi.product_id
        {where}
        GROUP BY o.id, o.session_id, o.ordered_by, o.status, o.created_at,
                 u.name, usr.first_name, usr.last_name
        ORDER BY o.created_at DESC
    """


def get_customer_orders(user_id):
    return fetch_all(_order_query("WHERE o.ordered_by = %s"), (user_id,))


def get_admin_orders():
    return fetch_all(_order_query(""))


def get_order_items(order_id):
    return fetch_all(
        """
        SELECT oi.product_id, oi.quantity, oi.unit_price, p.name
        FROM order_items oi
        INNER JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id = %s
        ORDER BY p.name
        """,
        (order_id,),
    )


def update_order_status(order_id, status, user_id=None):
    if status not in ORDER_STATUSES:
        raise POSValidationError("Select a valid order status.")

    def operation(cursor):
        cursor.execute(
            "SELECT * FROM orders WHERE id = %s FOR UPDATE",
            (order_id,),
        )
        order = cursor.fetchone()
        if order is None:
            raise POSNotFound("Order not found.")
        if user_id is not None and order["ordered_by"] != user_id:
            raise POSNotFound("Order not found.")
        if order["status"] == status:
            return order
        if order["status"] != "PENDING":
            raise POSValidationError("Only pending orders can change status.")
        if status == "CANCELLED":
            cursor.execute(
                """
                SELECT product_id, quantity
                FROM order_items
                WHERE order_id = %s
                """,
                (order_id,),
            )
            for item in cursor.fetchall():
                cursor.execute(
                    """
                    UPDATE products
                    SET stock_qty = stock_qty + %s
                    WHERE id = %s
                    """,
                    (item["quantity"], item["product_id"]),
                )
        cursor.execute(
            "UPDATE orders SET status = %s WHERE id = %s AND status = 'PENDING'",
            (status, order_id),
        )
        return order

    return _transaction(operation)
