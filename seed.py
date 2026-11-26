import datetime
from app.models import init_db, reset_db
from app.database import get_db
from app.security import hash_password
from app.engine.ledger import record_inward

def seed_database(db_path=None, clean=True):
    if clean:
        reset_db(db_path)
    else:
        init_db(db_path)

    with get_db(db_path) as conn:
        cur = conn.cursor()

        # 1. Seed Roles & Users (Section 3: Salesman A & B, Admin, Production, Auditor)
        users_data = [
            ("admin", "admin123", "admin", "Senthil Nathan (Factory Admin)", "admin@batchwisefoods.com"),
            ("sales_ravi", "sales123", "salesman", "Ravi Shankar (Salesman A - TN)", "ravi@batchwisefoods.com"),
            ("sales_kumar", "sales123", "salesman", "Kumar V (Salesman B - KA)", "kumar@batchwisefoods.com"),
            ("purchase_priya", "purchase123", "purchase_manager", "Priya Sharma (Procurement Desk)", "priya@batchwisefoods.com"),
            ("prod_suresh", "prod123", "production_manager", "Suresh K (Production Supervisor)", "suresh@batchwisefoods.com"),
            ("account_meera", "account123", "accountant", "Meera R (Chief Accountant)", "accountant@batchwisefoods.com"),
            ("audit_anita", "audit123", "auditor", "Anita Menon (Independent Auditor)", "anita@batchwisefoods.com"),
        ]

        for u in users_data:
            cur.execute("""
                INSERT OR IGNORE INTO users (username, password_hash, role, full_name, email)
                VALUES (?, ?, ?, ?, ?)
            """, (u[0], hash_password(u[1]), u[2], u[3], u[4]))

        # 2. Seed Master Items (Section 5: Murukku 200g, Flour, Oil, Spice Mix, Pouches, Cartons)
        items_data = [
            ("RM-FLOUR-01", "Refined Flour (Maida/Rice)", "raw_material", "kg", "1101", 20.0, 42.0, 0.0, 5.0),
            ("RM-OIL-01", "Refined Cooking Oil", "raw_material", "litre", "1507", 10.0, 140.0, 0.0, 5.0),
            ("RM-SPICE-01", "Salt and Spice Mix", "raw_material", "kg", "2103", 2.0, 200.0, 0.0, 5.0),
            ("PM-POUCH-200", "200g Food-Grade Printed Pouch", "packing_material", "piece", "3923", 100.0, 2.50, 0.0, 18.0),
            ("PM-POUCH-400", "400g Family Pack Printed Pouch", "packing_material", "piece", "3923", 50.0, 4.00, 0.0, 18.0),
            ("PM-CARTON-20", "Corrugated Carton (Holds 20 Pkts)", "packing_material", "piece", "4819", 10.0, 15.00, 0.0, 18.0),
            ("FG-MURUKKU-200", "Traditional Murukku 200g", "finished_good", "packet", "1905", 20.0, 28.00, 50.00, 5.0),
        ]

        item_ids = {}
        for it in items_data:
            cur.execute("""
                INSERT OR IGNORE INTO items (sku, name, category, uom, hsn_code, min_stock_alert, standard_cost, selling_price, gst_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, it)
            cur.execute("SELECT id FROM items WHERE sku = ?", (it[0],))
            item_ids[it[0]] = cur.fetchone()["id"]

        # 3. Seed BOM for FG-MURUKKU-200 (Expected output: 200 packets per batch)
        cur.execute("""
            INSERT OR IGNORE INTO boms (bom_code, name, finished_item_id, base_qty, uom, version, description)
            VALUES ('BOM-MURUKKU-200', 'Standard Recipe: Traditional Murukku 200g', ?, 200.0, 'packet', 1, 
                    'Standard batch recipe for 200 packets: 40kg flour, 10L oil, 1.2kg spice, 200 pouches, 10 cartons')
        """, (item_ids["FG-MURUKKU-200"],))
        cur.execute("SELECT id FROM boms WHERE bom_code = 'BOM-MURUKKU-200'")
        bom_id = cur.fetchone()["id"]

        bom_items_data = [
            (bom_id, item_ids["RM-FLOUR-01"], 40.0, 0.0, "Core flour mix (40 kg per 200 packets)"),
            (bom_id, item_ids["RM-OIL-01"], 10.0, 0.0, "Cooking oil (10 litres per 200 packets)"),
            (bom_id, item_ids["RM-SPICE-01"], 1.2, 0.0, "Salt & spice seasoning (1.2 kg per 200 packets)"),
            (bom_id, item_ids["PM-POUCH-200"], 200.0, 0.0, "Primary 200g pouches (200 pieces per batch)"),
            (bom_id, item_ids["PM-CARTON-20"], 10.0, 0.0, "Outer cartons (10 pieces per batch, 20 pkts/carton)"),
        ]
        for bi in bom_items_data:
            cur.execute("""
                INSERT OR IGNORE INTO bom_items (bom_id, component_item_id, quantity, scrap_percentage, notes)
                VALUES (?, ?, ?, ?, ?)
            """, bi)

        # 4. Seed Parties (Section 5: Retailer A in TN, Distributor B in KA)
        parties_data = [
            ("supplier", "Annam Agro Flour & Oil Mills", "33AAGCA1234F1Z8", "0431-2501111", "orders@annamagro.com", "Plot 18, SIDCO Estate, Tiruchirappalli", "Tamil Nadu", "33", 0.0, 0.0),
            ("supplier", "Supreme Packagings Pvt Ltd", "33AAGCS5678B1Z2", "0431-2502222", "sales@supremepack.com", "Plot 42, Industrial Complex, Madurai", "Tamil Nadu", "33", 0.0, 0.0),
            ("customer", "Retailer A Supermarkets", "33AABCR9999P1Z1", "044-28394444", "purchase@retailera.com", "14, Gandhi Road, T. Nagar, Chennai", "Tamil Nadu", "33", 50000.0, 0.0),
            ("customer", "Distributor B Wholesale Hub", "29AABCD8888Q1Z4", "080-28398888", "mgr@distributorb.com", "Sayyaji Rao Road, Bengaluru", "Karnataka", "29", 200000.0, 0.0),
        ]
        for p in parties_data:
            cur.execute("""
                INSERT OR IGNORE INTO parties (party_type, name, gstin, phone, email, address, state, state_code, credit_limit, current_balance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, p)

        # 5. Seed Mandatory Opening Stock (Section 5 Master Data)
        today_str = datetime.date.today().isoformat()
        exp_yr = (datetime.date.today() + datetime.timedelta(days=180)).isoformat()

        # Flour: 100 kg @ ₹42 opening rate
        record_inward(conn, item_ids["RM-FLOUR-01"], "RM-FLOUR-OPEN01", 100.0, 42.0, "opening_stock", 1, today_str, exp_yr, notes="Opening stock 100kg @ ₹42", reference_type="SEED")
        # Cooking oil: 30 L @ ₹140 opening rate
        record_inward(conn, item_ids["RM-OIL-01"], "RM-OIL-OPEN01", 30.0, 140.0, "opening_stock", 1, today_str, exp_yr, notes="Opening stock 30L @ ₹140", reference_type="SEED")
        # Salt and spice mix: 5 kg @ ₹200 opening rate
        record_inward(conn, item_ids["RM-SPICE-01"], "RM-SPICE-OPEN01", 5.0, 200.0, "opening_stock", 1, today_str, exp_yr, notes="Opening stock 5kg @ ₹200", reference_type="SEED")
        # 200g pouches: 500 pieces @ ₹2.50
        record_inward(conn, item_ids["PM-POUCH-200"], "PM-POUCH-OPEN01", 500.0, 2.50, "opening_stock", 1, today_str, exp_yr, notes="Opening stock 500 pcs @ ₹2.50", reference_type="SEED")
        # Cartons: 30 pieces @ ₹15.00
        record_inward(conn, item_ids["PM-CARTON-20"], "PM-CARTON-OPEN01", 30.0, 15.00, "opening_stock", 1, today_str, exp_yr, notes="Opening stock 30 pcs @ ₹15.00", reference_type="SEED")
        # Finished Murukku 200 g: 50 packets @ ₹30.00
        record_inward(conn, item_ids["FG-MURUKKU-200"], "FG-MURUKKU-OPEN01", 50.0, 30.00, "opening_stock", 1, today_str, exp_yr, notes="Opening stock 50 packets Murukku 200g", reference_type="SEED")

    print("[SUCCESS] BatchWise database seeded with NIT Trichy Murukku 200g benchmark master data.")

    # Auto-seed the complete 9-step benchmark scenario
    try:
        from app.services.benchmark_service import execute_benchmark_journey
        execute_benchmark_journey(db_path)
        print("[SUCCESS] NIT Trichy Murukku 200g benchmark scenario preloaded successfully.")
    except Exception as e:
        print(f"[NOTE] Operational journey init: {e}")

if __name__ == "__main__":
    seed_database()
