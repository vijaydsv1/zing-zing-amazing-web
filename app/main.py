from flask import Flask, request, jsonify  # <-- Only for /notify_whatsapp endpoint
from twilio.rest import Client as TwilioClient
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import razorpay
import sqlite3
from datetime import datetime
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
import os
load_dotenv()



# Initialize clients
app = FastAPI()
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware(SessionMiddleware, secret_key="supersecretkey")

# Replace these with your actual credentials
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
OWNER_WHATSAPP_NUMBER = os.getenv("OWNER_WHATSAPP_NUMBER")
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET") # Replace with real owner number


razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Pydantic model
class PaymentRequest(BaseModel):
    amount: int

@app.get("/paymentmethod", response_class=HTMLResponse)
async def payment_method(request: Request):
    grand_total = 500 * 100  # ₹500 in paise
    return templates.TemplateResponse("paymentmethod.html", {
        "request": request,
        "grand_total": grand_total,
        "key_id": RAZORPAY_KEY_ID
    })

@app.post("/create_order")
async def create_order(payment: PaymentRequest):
    try:
        amount_in_paise = payment.amount * 100
        data = {
            "amount": amount_in_paise,
            "currency": "INR",
            "payment_capture": 1
        }
        order = razorpay_client.order.create(data=data)
        return {
            "order_id": order['id'],
            "amount": order['amount'],
            "key": RAZORPAY_KEY_ID
        }
    except Exception as e:
        print("Order creation error:", e)
        return JSONResponse(status_code=500, content={"message": "Internal Server Error"})

@app.post("/payment_status")
async def payment_status(
    request: Request,
    razorpay_payment_id: str = Form(...),
    razorpay_order_id: str = Form(...),
    razorpay_signature: str = Form(...),
    name: str = Form(...),
    phone: str = Form(...),
    address: str = Form(...),
    live_location: str = Form(...),
    payment_method: str = Form(...),
    total_price: str = Form(...),
    items: str = Form(...)
):
    params_dict = {
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": razorpay_payment_id,
        "razorpay_signature": razorpay_signature
    }

    try:
        razorpay_client.utility.verify_payment_signature(params_dict)

        items_ordered = items.split(",")
        items_text = "\n".join([f"- {item.strip()}" for item in items_ordered])

        customer_msg = f"""
✅ Thank you {name} for your order!

📦 Items:
{items_text}

💳 Payment Method: {payment_method}
💰 Total: ₹{total_price}

📍 Delivery Address:
{address}

We'll deliver your order soon!
"""

        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=f"whatsapp:{phone}",
            body=customer_msg
        )

        owner_msg = f"""
🛒 New Order Received!

👤 Name: {name}
📞 Phone: {phone}
📍 Address: {address}
📌 Live Location: {live_location}

🛍️ Items Ordered:
{items_text}

💳 Payment: {payment_method}
💰 Total: ₹{total_price}

➡️ Please prepare and deliver the order.
"""

        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=OWNER_WHATSAPP_NUMBER,
            body=owner_msg
        )

        # Save order in DB
        store_order_in_db(name, items, total_price, payment_method, phone, address, live_location)

        return templates.TemplateResponse("success.html", {"request": request})

    except Exception as e:
        print("Signature verification failed:", e)
        return templates.TemplateResponse("failure.html", {"request": request})

@app.get("/payment_success", response_class=HTMLResponse)
async def payment_success(request: Request):
    return templates.TemplateResponse("success.html", {"request": request})

@app.get("/payment_failed", response_class=HTMLResponse)
async def payment_failed(request: Request):
    return templates.TemplateResponse("failure.html", {"request": request})


# ✅ Twilio WhatsApp Notification API
flask_app = Flask(__name__)

@flask_app.route('/notify_whatsapp', methods=['POST'])
def notify_whatsapp():
    data = request.json
    customer_name = data['customer_name']
    phone = data['phone']
    amount = data['amount']
    method = data['method']

    message_body = f"Hi {customer_name}, your payment of ₹{amount} via {method.upper()} has been received. Thank you for shopping with Zing² amaZing!"
    owner_message = f"New order alert! {customer_name} paid ₹{amount} via {method.upper()}."

    try:
        twilio = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        twilio.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=message_body,
            to=f'whatsapp:{phone}'
        )

        twilio.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=owner_message,
            to=OWNER_WHATSAPP_NUMBER
        )

        return jsonify({"status": "sent"})
    except Exception as e:
        return jsonify({"error": str(e)})

# Initialize DB at app startup
def init_db():
    conn = sqlite3.connect("orders.db")
    cursor = conn.cursor()

    # ✅ Create table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            items TEXT,
            total_price REAL,
            payment_method TEXT,
            phone TEXT,
            address TEXT,
            location TEXT,
            date_time TEXT
        )
    """)
    
    # ✅ Add column is_new only if it doesn't exist
    cursor.execute("PRAGMA table_info(orders)")
    columns = [col[1] for col in cursor.fetchall()]
    if "is_new" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN is_new INTEGER DEFAULT 1")
    
    conn.commit()
    conn.close()

# ✅ Call on startup
init_db()



# ✅ Store orders in SQLite DB
def store_order_in_db(name, items, total_price, payment_method, phone, address, location):
    conn = sqlite3.connect("orders.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO orders (name, items, total_price, payment_method, phone, address, location, date_time, is_new)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (name, items, total_price, payment_method, phone, address, location, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    notify_whatsapp()

    # ✅ Send WhatsApp notification
    notify_whatsapp()


ADMIN_CREDENTIALS = {
    "email": "jingjingamazing919@gmail.com",
    "password": "ZingZingamaZing@123"
}

# Show Admin Login Page
@app.get("/admin_login", response_class=HTMLResponse)
async def get_admin_login(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})


@app.post("/admin_login", response_class=HTMLResponse)
async def post_admin_login(request: Request, email: str = Form(...), password: str = Form(...)):
    if email == ADMIN_CREDENTIALS["email"] and password == ADMIN_CREDENTIALS["password"]:
        return RedirectResponse(url="/admin_dashboard", status_code=303)
    return templates.TemplateResponse("admin_login.html", {
        "request": request,
        "error": "Invalid credentials"
    })


@app.get("/admin_dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    conn = sqlite3.connect("orders.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # ✅ Make sure column exists for new order notifications
    cursor.execute("PRAGMA table_info(orders)")
    columns = [col[1] for col in cursor.fetchall()]
    if "is_new" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN is_new INTEGER DEFAULT 1")
        conn.commit()

    # ✅ Fetch all orders
    cursor.execute("SELECT * FROM orders ORDER BY date_time DESC")
    orders = cursor.fetchall()

    # ✅ Count only new orders
    cursor.execute("SELECT COUNT(*) as new_count FROM orders WHERE is_new = 1")
    new_orders_count = cursor.fetchone()["new_count"]

    # ✅ Mark all new orders as viewed
    cursor.execute("UPDATE orders SET is_new = 0 WHERE is_new = 1")
    conn.commit()
    conn.close()

    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "orders": orders,
        "new_orders_count": new_orders_count
    })


@app.get("/admin_logout", response_class=HTMLResponse)
async def admin_logout(request: Request):
    return RedirectResponse(url="/admin_login", status_code=302)


# Forgot Password - GET
@app.get("/forgot_password", response_class=HTMLResponse)
async def forgot_password_get(request: Request):
    return templates.TemplateResponse("forgot_password.html", {"request": request})


# Forgot Password - POST
@app.post("/forgot_password", response_class=HTMLResponse)
async def forgot_password_post(request: Request, email: str = Form(...), new_password: str = Form(...)):
    if email == ADMIN_CREDENTIALS["email"]:
        ADMIN_CREDENTIALS["password"] = new_password
        return HTMLResponse("<h3>Password updated successfully! <a href='/admin_login'>Login Now</a></h3>")
    else:
        return HTMLResponse("<h3 style='color:red;'>Invalid email. Access denied.</h3>")