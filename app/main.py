from flask import Flask, request, jsonify  # <-- Only for /notify_whatsapp endpoint (kept as you had it)
from twilio.rest import Client as TwilioClient
from fastapi import FastAPI, Request, Form, Header
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import razorpay
import sqlite3
from fastapi import FastAPI, Request, HTTPException
import hmac
import hashlib
import json
from datetime import datetime
from starlette.middleware.sessions import SessionMiddleware
from random import uniform
from dotenv import load_dotenv
from fastapi import Request, WebSocket, WebSocketDisconnect
load_dotenv()
import math
from geopy.distance import geodesic
from fastapi.templating import Jinja2Templates
import os

# Initialize clients & app
app = FastAPI()

# If your templates / static are inside app/templates and app/static adjust as needed.
# You originally set templates twice; the final assignment below uses BASE_DIR for correctness.
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.add_middleware(SessionMiddleware, secret_key="supersecretkey")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

@app.get("/test_static", response_class=HTMLResponse)
async def test_static(request: Request):
    return templates.TemplateResponse("test_static.html", {"request": request})

# Global variables to store delivery partner's location
partner_location = {"lat": 0.0, "lon": 0.0}

@app.get("/driver", response_class=HTMLResponse)
async def driver_page(request: Request):
    return templates.TemplateResponse("driver.html", {"request": request})

@app.post("/update_partner_location")
async def update_partner_location(request: Request):
    global partner_location
    data = await request.json()
    partner_location["lat"] = data.get("lat", 0.0)
    partner_location["lon"] = data.get("lon", 0.0)
    return {"status": "success"}

@app.get("/get_locations")
async def get_locations():
    return {"partner": partner_location}

# Fixed Owner Location (Puttur, Andhra Pradesh near Water Tank Street)
OWNER_LAT = 13.4506
OWNER_LON = 79.5534

@app.post("/calculate_total")
async def calculate_total(request: Request):
    try:
        data = await request.json()
        customer_lat = float(data.get("customer_lat", 0))
        customer_lon = float(data.get("customer_lon", 0))
        order_amount = float(data.get("order_amount", 0))

        # Default delivery charge
        delivery_charge = 40

        if customer_lat != 0 and customer_lon != 0:
            distance_km = geodesic((OWNER_LAT, OWNER_LON), (customer_lat, customer_lon)).km

            # Delivery calculation logic
            if distance_km <= 1:
                delivery_charge = 0
            else:
                delivery_charge = round((distance_km - 1) * 3, 2)

        total_amount = order_amount + delivery_charge

        return {
            "delivery_charge": delivery_charge,
            "total_amount": total_amount
        }

    except Exception as e:
        # If order_amount wasn't defined due to failure, fallback to 0
        try:
            fallback_total = float(order_amount) + 40
        except Exception:
            fallback_total = 40
        return {"error": str(e), "delivery_charge": 40, "total_amount": fallback_total}


# ✅ FRONTEND ROUTES (Added as per your request)
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/terms_and_conditions", response_class=HTMLResponse)
async def terms_and_conditions(request: Request):
    return templates.TemplateResponse("terms_and_conditions.html", {"request": request})

@app.get("/privacy_policy", response_class=HTMLResponse)
async def privacy_policy(request: Request):
    return templates.TemplateResponse("privacy_policy.html", {"request": request})

@app.get("/refund_and_cancellation", response_class=HTMLResponse)
async def refund_and_cancellation(request: Request):
    return templates.TemplateResponse("refund_and_cancellation.html", {"request": request})

@app.get("/menu", response_class=HTMLResponse)
async def menu(request: Request):
    return templates.TemplateResponse("menu.html", {"request": request})

@app.get("/cart", response_class=HTMLResponse)
async def cart(request: Request):
    return templates.TemplateResponse("cart.html", {"request": request})

@app.get("/order_details", response_class=HTMLResponse)
async def order_details(request: Request):
    return templates.TemplateResponse("order_details.html", {"request": request})

@app.get("/payment", response_class=HTMLResponse)
async def payment(request: Request):
    return templates.TemplateResponse("payment.html", {"request": request})

@app.get("/order_success", response_class=HTMLResponse)
async def order_success(request: Request):
    return templates.TemplateResponse("order_success.html", {"request": request})

@app.get("/track_delivery", response_class=HTMLResponse)
async def track_delivery(request: Request):
    return templates.TemplateResponse("track_delivery.html", {"request": request})

@app.get("/failure", response_class=HTMLResponse)
async def failure(request: Request):
    return templates.TemplateResponse("failure.html", {"request": request})

@app.get("/success", response_class=HTMLResponse)
async def success(request: Request):
    return templates.TemplateResponse("success.html", {"request": request})

@app.get("/thankyou", response_class=HTMLResponse)
async def thankyou(request: Request):
    return templates.TemplateResponse("thankyou.html", {"request": request})


# Replace these with your actual credentials
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
OWNER_WHATSAPP_NUMBER = os.getenv("OWNER_WHATSAPP_NUMBER")
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET") # Replace with real owner number

# Initialize Razorpay & Twilio safely (avoid crash if env not set)
razorpay_client = None
try:
    if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
        razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
except Exception as e:
    print("Razorpay init error:", e)
    razorpay_client = None

twilio_client = None
try:
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
except Exception as e:
    print("Twilio init error:", e)
    twilio_client = None

# Pydantic model
class PaymentRequest(BaseModel):
    amount: int

@app.get("/paymentmethod", response_class=HTMLResponse)
async def payment_method(request: Request):
    # ✅ Fetch from session or calculate dynamically
    cart_total = request.session.get("cart_total", 0)  # subtotal
    delivery_charge = request.session.get("delivery_charge", 0)  # delivery charges

    # Razorpay accepts amount in paise (multiply by 100)
    grand_total = (cart_total + delivery_charge) * 100

    return templates.TemplateResponse("paymentmethod.html", {
        "request": request,
        "grand_total": grand_total,
        "key_id": RAZORPAY_KEY_ID
    })

@app.post("/create_order")
async def create_order(payment: PaymentRequest):
    try:
        if not razorpay_client:
            return JSONResponse(status_code=500, content={"message": "Razorpay not configured"})
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
    razorpay_payment_id: str = Form(None),  # Made optional for Cash on Delivery
    razorpay_order_id: str = Form(None),    # Made optional for Cash on Delivery
    razorpay_signature: str = Form(None),   # Made optional for Cash on Delivery
    name: str = Form(...),
    phone: str = Form(...),
    address: str = Form(...),
    live_location: str = Form(...),
    payment_method: str = Form(...),
    total_price: str = Form(...),
    items: str = Form(...)
):
    # Check if this is a Razorpay payment or Cash on Delivery
    is_razorpay_payment = razorpay_payment_id and razorpay_order_id and razorpay_signature

    if is_razorpay_payment:
        # Verify Razorpay signature for online payments
        params_dict = {
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature
        }

        try:
            if not razorpay_client:
                raise Exception("Razorpay client not configured")

            razorpay_client.utility.verify_payment_signature(params_dict)
        except Exception as e:
            print("Signature verification failed:", e)
            return templates.TemplateResponse("failure.html", {"request": request})

    # Process order for both Razorpay and Cash on Delivery
    try:

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

        # Send to customer (if twilio configured)
        try:
            if twilio_client:
                twilio_client.messages.create(
                    from_=TWILIO_WHATSAPP_NUMBER,
                    to=f"whatsapp:{phone}",
                    body=customer_msg
                )
            else:
                print("Twilio not configured - skipping customer message")
        except Exception as e:
            print("Twilio customer send error:", e)

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

        # Send to owner (if twilio configured)
        try:
            if twilio_client:
                twilio_client.messages.create(
                    from_=TWILIO_WHATSAPP_NUMBER,
                    to=OWNER_WHATSAPP_NUMBER,
                    body=owner_msg
                )
            else:
                print("Twilio not configured - skipping owner message")
        except Exception as e:
            print("Twilio owner send error:", e)

        # Save order in DB
        store_order_in_db(name, items, total_price, payment_method, phone, address, live_location)

        return templates.TemplateResponse("success.html", {"request": request})

    except Exception as e:
        print("Signature verification failed or other error:", e)
        return templates.TemplateResponse("failure.html", {"request": request})

@app.get("/success", response_class=HTMLResponse)
async def payment_success(request: Request):
    return templates.TemplateResponse("success.html", {"request": request})

@app.get("/failure", response_class=HTMLResponse)
async def payment_failed(request: Request):
    return templates.TemplateResponse("failure.html", {"request": request})


# ✅ Twilio WhatsApp Notification API (robust: accepts JSON or form)
@app.post("/notify_whatsapp")
async def notify_whatsapp(request: Request):
    # Try JSON; if not present, try form data
    data = {}
    try:
        data = await request.json()
    except Exception:
        # fallback to form
        try:
            form = await request.form()
            data = dict(form)
        except Exception:
            data = {}

    if not data:
        return JSONResponse(status_code=400, content={"error": "Empty or invalid request body"})

    customer_name = data.get('customer_name', 'Customer')
    phone = data.get('phone')
    amount = data.get('amount', '0')
    method = data.get('method', 'unknown')
    items = data.get('items', 'Not provided')
    address = data.get('address', 'Not provided')
    live_location = data.get('live_location', 'Not provided')
    total_price = data.get('total_price', '0')
    payment_method = data.get('payment_method', 'Not specified')

    message_body = (
        f"Hi {customer_name}, your payment of ₹{amount} via {method.upper()} "
        f"has been received. Thank you for Ordering with Zing² amaZing!"
    )

    owner_message = (
        f"🛒 New order alert!\n\n"
        f"👤 Name: {customer_name}\n"
        f"📞 Phone: {phone}\n"
        f"📦 Items: {items}\n"
        f"🏠 Address: {address}\n"
        f"📍 Location: {live_location}\n"
        f"💰 Total Price: ₹{total_price}\n"
        f"💳 Payment Method: {payment_method}"
    )

    if not twilio_client:
        return JSONResponse(status_code=500, content={"error": "Twilio not configured on server"})

    try:
        if phone:
            twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                body=message_body,
                to=f'whatsapp:{phone}'
            )
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=owner_message,
            to=OWNER_WHATSAPP_NUMBER
        )

        return {"status": "sent"}
    except Exception as e:
        print("notify_whatsapp error:", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


# Initialize DB at app startup
def init_db():
    conn = sqlite3.connect("orders.db")
    cursor = conn.cursor()

    # ✅ Create table if it doesn't exist with consistent column names
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            phone TEXT,
            service TEXT,
            payment_method TEXT,
            date_time TEXT,
            status TEXT DEFAULT 'Pending',
            is_new INTEGER DEFAULT 1
        )
    """)

    # ✅ Check and add missing columns if table already exists
    cursor.execute("PRAGMA table_info(orders)")
    columns = [col[1] for col in cursor.fetchall()]

    if "email" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN email TEXT")
    if "service" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN service TEXT")
    if "status" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN status TEXT DEFAULT 'Pending'")
    if "is_new" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN is_new INTEGER DEFAULT 1")

    conn.commit()
    conn.close()

# ✅ Call on startup
init_db()


# ✅ Store orders in SQLite DB with proper column mapping
def store_order_in_db(name, items, total_price, payment_method, phone, address, location):
    conn = sqlite3.connect("orders.db")
    cursor = conn.cursor()

    # Map items to service field for admin dashboard compatibility
    service = items if items else "Order Items"

    cursor.execute("""
        INSERT INTO orders (name, email, phone, service, payment_method, date_time, status, is_new)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
    """, (name, "", phone, service, payment_method, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Pending"))

    order_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Broadcast new order to admin dashboard
    try:
        import asyncio
        asyncio.create_task(broadcast_new_order({
            "id": order_id,
            "name": name,
            "email": "",
            "phone": phone,
            "service": service,
            "payment_method": payment_method,
            "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "Pending"
        }))
    except Exception as e:
        print(f"Error broadcasting new order: {e}")

    return order_id

async def broadcast_new_order(order_data):
    """Broadcast new order to all connected admin clients"""
    await broadcast_to_admins({
        "type": "new_order",
        "order": order_data
    })


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
# Razorpay webhook secret from your dashboard
WEBHOOK_SECRET = "ZingZingamaZing123"

@app.post("/razorpay_webhook")
async def razorpay_webhook(request: Request):
    try:
        payload = await request.body()
        signature = request.headers.get("x-razorpay-signature")

        if not signature:
            raise HTTPException(status_code=400, detail="Signature missing")

        # Verify webhook signature
        expected_signature = hmac.new(
            WEBHOOK_SECRET.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_signature, signature):
            raise HTTPException(status_code=400, detail="Invalid signature")

        data = json.loads(payload)
        event_type = data.get("event")

        print(f"✅ Event received: {event_type}")
        print(json.dumps(data, indent=2))

        return {"status": "success"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
admin_clients = []

@app.websocket("/ws/admin")
async def admin_ws(websocket: WebSocket):
    await websocket.accept()
    admin_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # Keep connection alive
    except WebSocketDisconnect:
        admin_clients.remove(websocket)

async def broadcast_to_admins(message: dict):
    disconnected = []
    for client in admin_clients:
        try:
            await client.send_json(message)
        except:
            disconnected.append(client)
    for client in disconnected:
        admin_clients.remove(client)


@app.post("/webhook")
async def razorpay_webhook(request: Request, x_razorpay_signature: str = Header(None)):
    # Read the payload from the request body
    payload = await request.json()  # <-- This was missing

    # Optional: Verify Razorpay signature here
    # verify_signature(payload, x_razorpay_signature)

    event = payload.get("event")
    print(f"Received Event: {event}")

    # Broadcast to admin dashboards
    await broadcast_to_admins({
        "type": "razorpay_event",
        "event": event,
        "payload": payload
    })

    return {"status": "ok"}

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
    
# Simulated delivery partner location
delivery_lat = 20.5937
delivery_lon = 78.9629

@app.get("/get_locations")
async def get_locations():
    global delivery_lat, delivery_lon
    # Simulate movement by randomly changing coordinates
    delivery_lat += uniform(-0.0005, 0.0005)
    delivery_lon += uniform(-0.0005, 0.0005)

    return {
        "partner": {"lat": delivery_lat, "lon": delivery_lon}
    }

