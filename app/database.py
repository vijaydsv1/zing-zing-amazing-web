from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///./orders.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String)
    customer_phone = Column(String)
    customer_address = Column(Text)
    payment_method = Column(String)
    total_price = Column(String)
    live_location = Column(Text)
    items_ordered = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
import sqlite3
from datetime import datetime

DB_NAME = "app.db"

# Create database tables if they don't exist
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Customers Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL
        )
    ''')

    # Orders Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            order_items TEXT NOT NULL,
            total_price REAL NOT NULL,
            order_date TEXT NOT NULL,
            FOREIGN KEY(customer_id) REFERENCES customers(id)
        )
    ''')

    # Notifications Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_read INTEGER DEFAULT 0
        )
    ''')

    conn.commit()
    conn.close()


# Add a new customer
def add_customer(name, email, phone, address):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO customers (name, email, phone, address)
        VALUES (?, ?, ?, ?)
    ''', (name, email, phone, address))
    conn.commit()
    customer_id = cursor.lastrowid
    conn.close()
    return customer_id


# Add a new order & notification
def add_order(customer_id, order_items, total_price):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Store order
    cursor.execute('''
        INSERT INTO orders (customer_id, order_items, total_price, order_date)
        VALUES (?, ?, ?, ?)
    ''', (customer_id, order_items, total_price, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    # Store notification
    cursor.execute('''
        INSERT INTO notifications (message, created_at)
        VALUES (?, ?)
    ''', (f"New order placed by Customer ID {customer_id}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    conn.commit()
    conn.close()


# Get all orders with customer details
def get_all_orders():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT orders.id, customers.name, customers.email, customers.phone, customers.address,
               orders.order_items, orders.total_price, orders.order_date
        FROM orders
        JOIN customers ON orders.customer_id = customers.id
        ORDER BY orders.order_date DESC
    ''')
    orders = cursor.fetchall()
    conn.close()
    return orders


# Get unread notifications
def get_unread_notifications():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, message, created_at FROM notifications WHERE is_read = 0 ORDER BY created_at DESC
    ''')
    notifications = cursor.fetchall()
    conn.close()
    return notifications


# Mark a notification as read
def mark_notification_read(notification_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE notifications SET is_read = 1 WHERE id = ?
    ''', (notification_id,))
    conn.commit()
    conn.close()


init_db()


def init_db():
    Base.metadata.create_all(bind=engine)
