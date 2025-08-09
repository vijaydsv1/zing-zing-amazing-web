# database.py
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
from twilio.rest import Client
import os

# -------------------- Database Setup --------------------
DATABASE_URL = "sqlite:///customers.db"  # SQLite DB file

Base = declarative_base()

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String, nullable=False)
    service = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    orders = relationship("Order", back_populates="customer")

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    items = Column(Text, nullable=False)
    total_price = Column(String, nullable=False)
    payment_method = Column(String, nullable=False)
    order_date = Column(DateTime, default=datetime.utcnow)
    is_new = Column(Boolean, default=True)

    customer = relationship("Customer", back_populates="orders")

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_read = Column(Boolean, default=False)

# Create DB engine & tables
engine = create_engine(DATABASE_URL, echo=False)
Base.metadata.create_all(engine)

# Session factory
SessionLocal = sessionmaker(bind=engine)

# -------------------- Twilio WhatsApp Notification --------------------
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "your_account_sid")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "your_auth_token")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")  # Twilio sandbox
TWILIO_TEST_MODE = True  # Change to False in production

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def send_whatsapp_message(to_number, message):
    """Send a WhatsApp message via Twilio."""
    if TWILIO_TEST_MODE:
        print(f"[TEST MODE] WhatsApp to {to_number}: {message}")
        return True
    try:
        client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            body=message,
            to=f"whatsapp:{to_number}"
        )
        print(f"✅ WhatsApp sent to {to_number}")
        return True
    except Exception as e:
        print(f"❌ WhatsApp send failed: {e}")
        return False

# -------------------- Database Functions --------------------
def add_customer(name, phone, email, service):
    """Add a customer to DB."""
    session = SessionLocal()
    try:
        customer = Customer(name=name, phone=phone, email=email, service=service)
        session.add(customer)
        session.commit()
        print(f"✅ Customer '{name}' added.")
        return customer.id
    except Exception as e:
        session.rollback()
        print(f"❌ Error adding customer: {e}")
    finally:
        session.close()

def add_order(customer_id, items, total_price, payment_method):
    """Add an order & admin notification."""
    session = SessionLocal()
    try:
        order = Order(
            customer_id=customer_id,
            items=items,
            total_price=total_price,
            payment_method=payment_method
        )
        session.add(order)

        # Create admin notification
        customer = session.query(Customer).filter(Customer.id == customer_id).first()
        notif_msg = f"New order from {customer.name} ({customer.phone})"
        notification = Notification(message=notif_msg)
        session.add(notification)

        session.commit()

        # Send WhatsApp to customer
        send_whatsapp_message(
            customer.phone,
            f"Hello {customer.name}, your order for '{items}' "
            f"totaling ₹{total_price} has been received. Payment method: {payment_method}."
        )

        print(f"✅ Order placed by {customer.name} and notification created.")
    except Exception as e:
        session.rollback()
        print(f"❌ Error adding order: {e}")
    finally:
        session.close()

def get_all_orders():
    """Fetch all orders with customer details."""
    session = SessionLocal()
    try:
        orders = session.query(Order).join(Customer).all()
        return orders
    finally:
        session.close()

def get_unread_notifications():
    """Fetch all unread admin notifications."""
    session = SessionLocal()
    try:
        return session.query(Notification).filter_by(is_read=False).order_by(Notification.created_at.desc()).all()
    finally:
        session.close()

def mark_notification_read(notification_id):
    """Mark a notification as read."""
    session = SessionLocal()
    try:
        notif = session.query(Notification).get(notification_id)
        if notif:
            notif.is_read = True
            session.commit()
    finally:
        session.close()

# -------------------- Example Usage --------------------
if __name__ == "__main__":
    # Create a test customer
    cust_id = add_customer("John Doe", "+919999999999", "john@example.com", "Plumbing Service")

    # Create a test order
    add_order(cust_id, "Pipe repair", "500", "Cash on Delivery")

    # Show unread notifications
    for notif in get_unread_notifications():
        print(f"[NOTIF] {notif.message} at {notif.created_at}")
