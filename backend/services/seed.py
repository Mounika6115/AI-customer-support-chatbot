from datetime import datetime, timedelta
from models import (db, User, ProductCategory, Product, Order, OrderItem,
                    Payment, ReturnRequest, Refund, Offer, Warranty, KnowledgeBase, Notification)


def _get_or_create_category(name, description=""):
    c = ProductCategory.query.filter_by(name=name).first()
    if not c:
        c = ProductCategory(name=name, description=description)
        db.session.add(c)
        db.session.flush()
    return c


def seed():
    for name, email, role in [
        ("Demo Customer", "customer@example.com", "customer"),
        ("Admin", "admin@example.com", "admin"),
    ]:
        user = User.query.filter_by(email=email).first()
        if user is None:
            user = User(name=name, email=email, role=role, phone="+91-9000000001")
            db.session.add(user)
        user.name = name
        user.role = role
        if not user.phone:
            user.phone = "+91-9000000001"
        try:
            ok = user.check_password("Demo123!")
        except Exception:
            ok = False
        if not user.password_hash or not ok:
            user.set_password("Demo123!")
    db.session.flush()

    cats = {}
    for cn, desc in [("Smartphones", "Mobile phones"), ("Laptops", "Laptops"),
                     ("Headphones", "Audio"), ("Smart Watches", "Wearables"), ("Tablets", "Tablets"),
                     ("TVs", "Televisions"), ("Air Conditioners", "Air conditioners")]:
        cats[cn] = _get_or_create_category(cn, desc)
    db.session.flush()

    customer = User.query.filter_by(email="customer@example.com").first()

    catalogue = [
        # product_name, brand, category, price, original, stock, rating, warranty, specs
        ("Nova X1 Smartphone", "Nova", "Smartphones", 699.0, 799.0, 25, 4.5, "1 year",
         "6.5-inch display, 128GB storage, 5000mAh battery."),
        ("Galaxy M35 5G", "Samsung", "Smartphones", 24999.0, 29999.0, 40, 4.3, "1 year",
         "6.6-inch Super AMOLED, 6000mAh battery, 50MP camera."),
        ("Galaxy S24 FE", "Samsung", "Smartphones", 29999.0, 59999.0, 15, 4.6, "1 year",
         "6.7-inch AMOLED, Exynos 2400e, 50MP OIS camera."),
        ("Galaxy A15", "Samsung", "Smartphones", 16999.0, 19999.0, 60, 4.2, "1 year",
         "6.5-inch Super AMOLED, 5000mAh battery, 50MP camera."),
        ("AeroBook 14", "Aero", "Laptops", 1099.0, 1299.0, 12, 4.4, "2 years",
         "14-inch laptop, 16GB RAM, 512GB SSD."),
        ("Pulse Pro", "Pulse", "Headphones", 149.0, 199.0, 100, 4.1, "1 year",
         "Over-ear Bluetooth headphones, 40h battery, noise isolation."),
        ("Orbit Watch", "Orbit", "Smart Watches", 249.0, 299.0, 50, 4.0, "1 year",
         "1.85-inch display, heart-rate + SpO2 tracking, 7-day battery."),
        ("TabOne 11", "TabOne", "Tablets", 499.0, 599.0, 30, 4.2, "1 year",
         "11-inch 2K display, 8GB RAM, 256GB storage."),
        ("VisionMax 43 4K TV", "Sony", "TVs", 42999.0, 54999.0, 20, 4.5, "2 years",
         "43-inch 4K Ultra HD Smart TV, Dolby Vision + Atmos, 3 HDMI, 2 USB, Wi-Fi."),
        ("NovaView 32 HD TV", "Nova", "TVs", 18999.0, 24999.0, 35, 4.2, "1 year",
         "32-inch HD Ready Smart TV, 2 HDMI, 1 USB, screen mirroring."),
        ("FrostCool 1.5T Split AC", "Volt", "Air Conditioners", 35999.0, 45999.0, 18, 4.4, "1 year product, 5 years compressor",
         "1.5 Ton 5-star split AC, inverter compressor, copper condenser, anti-dust filter."),
        ("ChillPro 1T Window AC", "Volt", "Air Conditioners", 28499.0, 33999.0, 22, 4.1, "1 year product, 5 years compressor",
         "1 Ton 3-star window AC, copper condenser, auto-restart, sleep mode."),
    ]
    for row in catalogue:
        (pname, brand, cat, price, orig, stock, rating, warr) = row[:8]
        specs = row[8] if len(row) > 8 else "Demo specifications. See store page for full specs."
        p = Product.query.filter_by(product_name=pname).first() or \
            Product.query.filter_by(name=pname).first()
        if not p:
            p = Product(product_name=pname, name=pname)
            db.session.add(p)
        p.product_name = pname
        p.name = pname
        p.brand = brand
        p.category = cat
        p.category_id = cats[cat].id if cat in cats else None
        p.description = f"{pname} by {brand} - genuine store product."
        p.price = price
        p.original_price = orig
        p.discount = round((orig - price) * 100 / orig, 1) if orig else 0
        p.stock_quantity = stock
        p.rating = rating
        p.warranty_period = warr
        p.warranty = warr
        p.specifications = specs
        p.return_policy = "30-day return"
        p.availability = stock > 0
        p.image_url = ""
    db.session.flush()

    if customer and not Order.query.filter_by(customer_id=customer.id).first():
        nova = Product.query.filter_by(product_name="Nova X1 Smartphone").first()
        pulse = Product.query.filter_by(product_name="Pulse Pro").first()
        o = Order(order_number="RD100234", customer_id=customer.id, total_amount=699.0,
                  payment_status="PAID", order_status="SHIPPED",
                  delivery_status="OUT_FOR_DELIVERY",
                  delivery_address="Bengaluru, Karnataka",
                  expected_delivery_date="2026-10-07",
                  tracking_number="TRK100234",
                  product="Nova X1 Smartphone", quantity=1, price=699.0,
                  order_date="2026-09-25")
        db.session.add(o)
        db.session.flush()
        if nova:
            db.session.add(OrderItem(order_id=o.id, product_id=nova.id, quantity=1, price=699.0))
            db.session.add(Payment(order_id=o.id, customer_id=customer.id, amount=699.0,
                                   method="CARD", status="PAID", transaction_id="TXN100234"))
            # processing refund example
            db.session.add(Refund(order_id=o.id, customer_id=customer.id, amount=699.0,
                                  status="PROCESSING", reason="Customer reported refund not received"))
            db.session.add(Warranty(product_id=nova.id, order_id=o.id, customer_id=customer.id,
                                    period="1 year", status="ACTIVE", expires_at="2027-09-25"))
        # second, delivered order so return-eligibility + warranty-claim flows are demoable
        if pulse:
            o2 = Order(order_number="RD100235", customer_id=customer.id, total_amount=149.0,
                       payment_status="PAID", order_status="DELIVERED",
                       delivery_status="DELIVERED",
                       delivery_address="Bengaluru, Karnataka",
                       expected_delivery_date="2026-09-20",
                       tracking_number="TRK100235",
                       product="Pulse Pro", quantity=1, price=149.0,
                       order_date="2026-09-12")
            db.session.add(o2)
            db.session.flush()
            db.session.add(OrderItem(order_id=o2.id, product_id=pulse.id, quantity=1, price=149.0))
            db.session.add(Payment(order_id=o2.id, customer_id=customer.id, amount=149.0,
                                   method="UPI", status="PAID", transaction_id="TXN100235"))
            db.session.add(Warranty(product_id=pulse.id, order_id=o2.id, customer_id=customer.id,
                                    period="1 year", status="ACTIVE", expires_at="2027-09-12"))
    db.session.flush()

    if not Offer.query.first():
        db.session.add(Offer(title="Festive Sale - 10% off Smartphones",
                             description="10% off on all smartphones this week.",
                             discount_percent=10.0, active=True))
        db.session.add(Offer(title="Samsung Days", description="Extra exchange bonus on Samsung phones.",
                             discount_percent=5.0, active=True))

    if not KnowledgeBase.query.first():
        for title, cat, content in [
            ("Return Policy", "returns", "Eligible products may be returned within 30 days of delivery. Orders already cancelled, returned, or refunded cannot be returned again. Start a return from chat with your order number."),
            ("Refund Policy", "refunds", "Once a return pickup is complete or a cancellation is confirmed, refunds are initiated within 24 hours and typically reach your account in 5-7 business days. Track status with 'refund status'."),
            ("Shipping Policy", "delivery", "Delivery dates are estimates. Verified order status should be read from the order record."),
            ("Warranty Policy", "warranty", "Warranty length depends on the product record (usually 1 year, 2 years on laptops). Claim warranty from chat with your order number; pickup is scheduled after approval."),
            ("Installation & Setup", "installation", "Unbox, charge fully, follow the in-box quick-start guide. For technician installation visits, raise a service request of type INSTALLATION from chat."),
            ("Damaged Product Help", "damaged", "If your product arrived damaged or defective, report it in chat with your order number and a short description. A service request is created and pickup is scheduled after approval."),
            ("Payment Methods", "payment", "Demo store accepts major cards. Payment status is verified from the order record."),
        ]:
            db.session.add(KnowledgeBase(title=title, category=cat, content=content))

    # One-time cleanup of pre-removal human-agent state so old DBs just work.
    try:
        from models import Conversation, Ticket
        for c in Conversation.query.filter(
                Conversation.status.in_(["WAITING_FOR_AGENT", "AGENT_ACTIVE", "WAITING_FOR_CUSTOMER"])).all():
            c.status = "AI_ACTIVE"
        for t in Ticket.query.filter_by(status="WAITING_FOR_AGENT").all():
            t.status = "OPEN"
        db.session.commit()
    except Exception:
        db.session.rollback()
