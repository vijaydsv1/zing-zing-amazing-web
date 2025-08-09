# main.py (updated)
from flask import Flask, request, jsonify  # kept for compatibility (you used it earlier)
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
from random import uniform
from dotenv import load_dotenv
import os
load_dotenv()
import math
from geopy.distance import geodesic
from jinja2 import TemplateNotFound

# -------------------------
# App / templates / static
# -------------------------
app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# choose templates dir: prefer app/templates then templates
if os.path.isdir(os.path.join(BASE_DIR, "app", "templates")):
    templates_dir = os.path.join(BASE_DIR, "app", "templates")
elif os.path.isdir(os.path.join(BASE_DIR, "templates")):
    templates_dir = os.path.join(BASE_DIR, "templates")
else:
    # fallback: use BASE_DIR/templates (will show helpful message if missing)
    templates_dir = os.path.join(BASE_DIR, "templates")

# choose static dir similarly
if os.path.isdir(os.path.join(BASE_DIR, "app", "static")):
    static_dir = os.path.join(BASE_DIR, "app", "static")
elif os.path.isdir(os.path.join(BASE_DIR, "static")):
    static_dir = os.path.join(BASE_DIR, "static")
else:
    static_dir = os.path.join(BASE_DIR, "static")  # might not exist

print(f"[INFO] Using templates dir: {templates_dir}")
print(f"[INFO] Using static dir: {static_dir}")

# mount static if exists (FastAPI will error if directory doesn't exist)
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
else:
    print(f"[WARN] Static directory not found at {static_dir} (continuing without mounted static)")

templates = Jinja2Templates(directory=templates_dir)
app.add_middleware(SessionMiddleware, secret_key="supersecretkey")

# -------------------------
# Utility: Smart template loader
# -------------------------
def smart_template_response(request: Request, base_name: str):
    """
    Try multiple filename variants for a template to avoid TemplateNotFound errors.
    E.g. for base_name='privacy-policy' it will try:
      - privacy-policy.html
      - privacy_policy.html
      - privacy-policy.html (lowercased)
    If none found, returns a friendly HTMLResponse with instructions (404).
    """
    candidates = [
        f"{base_name}.html",
        f"{base_name.replace('-', '_')}.html",
        f"{base_name.replace('_', '-')}.html",
        f"{base_name.lower()}.html"
    ]

    for candidate in candidates:
        try:
            # attempt to load via Jinja environment to confirm existence
            templates.env.get_template(candidate)
            return templates.TemplateResponse(candidate, {"request": request})
        except TemplateNotFound:
            continue

    # none found -> friendly 404
    debug_paths = [
        os.path.join(templates_dir, c) for c in candidates
    ]
    body = f"""
    <html>
      <head><title>Template Not Found</title></head>
      <body style="font-family:Arial,sans-serif; padding:20px;">
        <h2>Template not found</h2>
        <p>The server tried to load any of these templates but none were found:</p>
        <ul>
          {''.join(f'<li>{p}</li>' for p in debug_paths)}
        </ul>
        <p>Please upload the file to the templates directory or rename it appropriately.</p>
        <p><a href="/">Return home</a></p>
      </body>
    </html>
    """
    return HTMLResponse(content=body, status_code=404)

# -------------------------
# Simple Twilio sync helper
# -------------------------
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
OWNER_WHATSAPP_NUMBER = os.getenv("OWNER_WHATSAPP_NUMBER")
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

# safe init of external clients
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

def send_whatsapp_sync(to_number: str, message: str) -> bool:
    """
    Send WhatsApp message using Twilio synchronously.
    Returns True on success, False otherwise.
    """
    if not twilio_client:
        print("[WARN] Twilio not configured; cannot send WhatsApp.")
        return False

    if not to_number:
        print("[WARN] No 'to' number provided for WhatsApp send.")
        return False

    try:
        # ensure number doesn't include 'whatsapp:' prefix
        to = to_number.replace("whatsapp:", "").strip()
        if not to.startswith("+"):
            # Twilio requires E.164 — assume Indian if not provided (optional)
            to = "+" + to

        msg = twilio_client.messages.create(
            body=message,
            from_=TWILIO_WHATSAPP_NUMBER,
            to=f"whatsapp:{to}"
        )
        print(f"[INFO] WhatsApp sent, sid={getattr(msg, 'sid', 'n/a')}")
        return True
    except Exception as e:
        print("[ERROR] send_whatsapp_sync failed:", e)
        return False

# -------------------------
# Delivery / location globals
# -------------------------
partner_location = {"lat": 0.0, "lon": 0.0}

@app.post("/update_partner_location")
async def update_partner_location(request: Request):
    global partner_location
    data = await request.json()
    partner_location["lat"] = float(data.get("lat", 0.0))
    partner_location["lon"] = float(data.get("lon", 0.0))
    return {"status": "success"}

# Single authoritative get_locations route (merged behavior)
delivery_lat = 20.5937
delivery_lon = 78.9629

@app.get("/get_locations")
async def get_locations():
    """
    Returns simulated delivery partner location (moves a little each call).
    If partner_location has been updated via /update_partner_location, return that instead.
    """
    global delivery_lat, delivery_lon, partner_location
    # If partner_location was updated by driver, prefer it
    if partner_location.get("lat") not in (0.0, None) and partner_location.get("lon") not in (0.0, None):
        return {"partner": partner_location}

    # else simulate movement
    delivery_lat += uniform(-0.0005, 0.0005)
    delivery_lon += uniform(-0.0005, 0.0005)
    return {"partner": {"lat": delivery_lat, "lon": delivery_lon}}

# Fixed Owner Location
OWNER_LAT = 13.4506
OWNER_LON = 79.5534

@app.post("/calculate_total")
async def calculate_total(request: Request):
    try:
        data = await request.json()
        customer_lat = float(data.get("customer_lat", 0))
        customer_lon = float(data.get("customer_lon", 0))
        order_amount = float(data.get("order_amount", 0))
        delivery_charge = 40

        if customer_lat != 0 and customer_lon != 0:
            distance_km = geodesic((OWNER_LAT, OWNER_LON), (customer_lat, customer_lon)).km
            if distance_km <= 1:
                delivery_charge = 0
            else:
                delivery_charge = round((distance_km - 1) * 3, 2)

        total_amount = order_amount + delivery_charge
        return {"delivery_charge": delivery_charge, "total_amount": total_amount}
    except Exception as e:
        print("[ERROR] calculate_total:", e)
        try:
            fallback_total = float(order_amount) + 40
        except Exception:
            fallback_total = 40
        return {"error": str(e), "delivery_charge": 40, "total_amount": fallback_total}

# -------------------------
# Frontend routes (robust template loading)
# -------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return smart_template_response(request, "index")

# Provide both underline and dash url variants and robust filename lookup
@app.get("/terms_and_conditions", response_class=HTMLResponse)
@app.get("/terms_and_conditions", response_class=HTMLResponse)
async def terms_handler(request: Request):
    return smart_template_response(request, "terms_and_conditions")

@app.get("/privacy_policy", response_class=HTMLResponse)
@app.get("/privacy_policy", response_class=HTMLResponse)
async def privacy_handler(request: Request):
    return smart_template_response(request, "privacy_policy")

@app.get("/refund_and_cancellation", response_class=HTMLResponse)
@app.get("/refund_and_cancellation", response_class=HTMLResponse)
async def refund_handler(request: Request):
    return smart_template_response(request, "refund_and_cancellation")

@app.get("/menu", response_class=HTMLResponse)
async def menu(request: Request):
    return smart_template_response(request, "menu")

@app.get("/cart", response_class=HTMLResponse)
async def cart(request: Request):
    return smart_template_response(request, "cart")

@app.get("/order_details", response_class=HTMLResponse)
@app.get("/order-details", response_class=HTMLResponse)
async def order_details(request: Request):
    return smart_template_response(request, "order_details")

@app.get("/payment", response_class=HTMLResponse)
async def payment(request: Request):
    return smart_template_response(request, "payment")

@app.get("/order_success", response_class=HTMLResponse)
async def order_success(request: Request):
    return smart_template_response(request, "order_success")

@app.get("/track_delivery", response_class=HTMLResponse)
async def track_delivery(request: Request):
    return smart_template_response(request, "track_delivery")

@app.get("/failure", response_class=HTMLResponse)
async def failure(request: Request):
    return smart_template_response(request, "failure")

@app.get("/success", response_class=HTMLResponse)
async def success(request: Request):
    return smart_template_response(request, "success")

@app.get("/thankyou", response_class=HTMLResponse)
async def thankyou(request: Request):
    return smart_template_response(request, "thankyou")

# -------------------------
# Payment & Twilio / Razorpay flows (kept your logic but guarded)
# -------------------------
class PaymentRequest(BaseModel):
    amount: int

@app.get("/paymentmethod", response_class=HTMLResponse)
async def payment_method(request: Request):
    cart_total = request.session.get("cart_total", 0)
    delivery_charge = request.session.get("delivery_charge", 0)
    grand_total = (cart_total + delivery_charge) * 100
    return templates.TemplateResponse("paymentmethod.html", {"request": request, "grand_total": grand_total, "key_id": RAZORPAY_KEY_ID})

@app.post("/create_order")
async def create_order(payment: PaymentRequest):
    try:
        if not razorpay_client:
            return JSONResponse(status_code=500, content={"message": "Razorpay not configured"})
        amount_in_paise = payment.amount * 100
        data = {"amount": amount_in_paise, "currency": "INR", "payment_capture": 1}
        order = razorpay_client.order.create(data=data)
        return {"order_id": order['id'], "amount": order['amount'], "key": RAZORPAY_KEY_ID}
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
    params_dict = {"razorpay_order_id": razorpay_order_id, "razorpay_payment_id": razorpay_payment_id, "razorpay_signature": razorpay_signature}
    try:
        if not razorpay_client:
            raise Exception("Razorpay client not configured")

        razorpay_client.utility.verify_payment_signature(params_dict)
        items_ordered = items.split(",")
        items_text = "\n".join([f"- {item.strip()}" for item in items_ordered])

        customer_msg = f"""✅ Thank you {name} for your order!

📦 Items:
{items_text}

💳 Payment Method: {payment_method}
💰 Total: ₹{total_price}

📍 Delivery Address:
{address}

We'll deliver your order soon!
"""
        # customer notification
        try:
            send_whatsapp_sync(phone, customer_msg)
        except Exception as e:
            print("Error sending customer WhatsApp:", e)

        owner_msg = f"""🛒 New Order Received!

👤 Name: {name}
📞 Phone: {phone}
📍 Address: {address}
📌 Live Location: {live_location}

🛍️ Items Ordered:
{items_text}

💳 Payment: {payment_method}
💰 Total: ₹{total_price}
"""
        try:
            send_whatsapp_sync(OWNER_WHATSAPP_NUMBER, owner_msg)
        except Exception as e:
            print("Error sending owner WhatsApp:", e)

        # Save order in DB (this will also notify via WhatsApp as per store_order_in_db)
        store_order_in_db(name, items, total_price, payment_method, phone, address, live_location)

        return templates.TemplateResponse("success.html", {"request": request})
    except Exception as e:
        print("Signature verification failed or other error:", e)
        return templates.TemplateResponse("failure.html", {"request": request})

# Robust notify_whatsapp endpoint (accepts JSON or form)
@app.post("/notify_whatsapp")
async def notify_whatsapp(request: Request):
    data = {}
    try:
        data = await request.json()
    except Exception:
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

    message_body = f"Hi {customer_name}, your payment of ₹{amount} via {method.upper()} has been received. Thank you for Ordering with Zing² amaZing!"
    owner_message = f"🛒 New order alert!\n\n👤 Name: {customer_name}\n📞 Phone: {phone}\n📦 Items: {items}\n🏠 Address: {address}\n📍 Location: {live_location}\n💰 Total Price: ₹{total_price}\n💳 Payment Method: {payment_method}"

    if not twilio_client:
        return JSONResponse(status_code=500, content={"error": "Twilio not configured on server"})

    try:
        if phone:
            send_whatsapp_sync(phone, message_body)
        send_whatsapp_sync(OWNER_WHATSAPP_NUMBER, owner_message)
        return {"status": "sent"}
    except Exception as e:
        print("notify_whatsapp error:", e)
        return JSONResponse(status_code=500, content={"error": str(e)})

# -------------------------
# Database init and store order (with sync WhatsApp call)
# -------------------------
def init_db():
    conn = sqlite3.connect("orders.db")
    cursor = conn.cursor()
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
            date_time TEXT,
            is_new INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()

init_db()

def store_order_in_db(name, items, total_price, payment_method, phone, address, location):
    conn = sqlite3.connect("orders.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO orders (name, items, total_price, payment_method, phone, address, location, date_time, is_new)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (name, items, total_price, payment_method, phone, address, location, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

    # Synchronous notifications:
    try:
        # notify customer
        cust_msg = f"✅ Hi {name}, your order of {items} (₹{total_price}) is confirmed. We'll deliver to: {address}."
        send_whatsapp_sync(phone, cust_msg)
    except Exception as e:
        print("Error notifying customer (store_order_in_db):", e)

    try:
        # notify owner
        owner_msg = f"🛒 ORDER: {name} | {phone} | ₹{total_price} | {items} | {address}"
        send_whatsapp_sync(OWNER_WHATSAPP_NUMBER, owner_msg)
    except Exception as e:
        print("Error notifying owner (store_order_in_db):", e)

# -------------------------
# Admin / login / dashboard (kept your logic)
# -------------------------
ADMIN_CREDENTIALS = {"email": "jingjingamazing919@gmail.com", "password": "ZingZingamaZing@123"}

@app.get("/admin_login", response_class=HTMLResponse)
async def get_admin_login(request: Request):
    return smart_template_response(request, "admin_login")

@app.post("/admin_login", response_class=HTMLResponse)
async def post_admin_login(request: Request, email: str = Form(...), password: str = Form(...)):
    if email == ADMIN_CREDENTIALS["email"] and password == ADMIN_CREDENTIALS["password"]:
        return RedirectResponse(url="/admin_dashboard", status_code=303)
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": "Invalid credentials"})

@app.get("/admin_dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    conn = sqlite3.connect("orders.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(orders)")
    columns = [col[1] for col in cursor.fetchall()]
    if "is_new" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN is_new INTEGER DEFAULT 1")
        conn.commit()

    cursor.execute("SELECT * FROM orders ORDER BY date_time DESC")
    orders = cursor.fetchall()
    cursor.execute("SELECT COUNT(*) as new_count FROM orders WHERE is_new = 1")
    row = cursor.fetchone()
    new_orders_count = row["new_count"] if row is not None else 0
    cursor.execute("UPDATE orders SET is_new = 0 WHERE is_new = 1")
    conn.commit()
    conn.close()
    return templates.TemplateResponse("admin_dashboard.html", {"request": request, "orders": orders, "new_orders_count": new_orders_count})

@app.get("/admin_logout", response_class=HTMLResponse)
async def admin_logout(request: Request):
    return RedirectResponse(url="/admin_login", status_code=302)

@app.get("/forgot_password", response_class=HTMLResponse)
async def forgot_password_get(request: Request):
    return smart_template_response(request, "forgot_password")

@app.post("/forgot_password", response_class=HTMLResponse)
async def forgot_password_post(request: Request, email: str = Form(...), new_password: str = Form(...)):
    if email == ADMIN_CREDENTIALS["email"]:
        ADMIN_CREDENTIALS["password"] = new_password
        return HTMLResponse("<h3>Password updated successfully! <a href='/admin_login'>Login Now</a></h3>")
    else:
        return HTMLResponse("<h3 style='color:red;'>Invalid email. Access denied.</h3>")


