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

        # 1. Seed 5 Business Roles
        users_data = [
            ("admin", "admin123", "admin", "System Administrator", "admin@batchwise.com"),
            ("sales_ravi", "sales123", "salesman", "Ravi Shankar (Field Sales)", "ravi@batchwise.com"),
            ("purchase_priya", "purchase123", "purchase_manager", "Priya Sharma (Procurement)", "priya@batchwise.com"),
            ("prod_kumar", "prod123", "production_manager", "Kumar V (Plant Supervisor)", "kumar@batchwise.com"),
            ("audit_anita", "audit123", "auditor", "Anita Menon (Internal Auditor & Accounts)", "anita@batchwise.com"),
        ]

        for u in users_data:
            cur.execute("""
                INSERT OR IGNORE INTO users (username, password_hash, role, full_name, email)
                VALUES (?, ?, ?, ?, ?)
            """, (u[0], hash_password(u[1]), u[2], u[3], u[4]))

        # 2. Seed Master Items
        items_data = [
            ("RM-FLOUR-01", "Refined Wheat Flour Grade A", "raw_material", "kg", "1101", 100.0, 30.0, 0.0, 5.0),
            ("RM-SUGAR-01", "Refined Cane Sugar", "raw_material", "kg", "1701", 20.0, 42.0, 0.0, 5.0),
            ("RM-YEAST-01", "Active Baker's Yeast & Salt Premix", "raw_material", "kg", "2102", 10.0, 120.0, 0.0, 5.0),
            ("PM-POUCH-400", "Food-Grade Bread Pouch 400g", "packing_material", "unit", "3923", 200.0, 2.50, 0.0, 18.0),
            ("PM-POUCH-800", "Food-Grade Family Bread Pouch 800g", "packing_material", "unit", "3923", 100.0, 3.80, 0.0, 18.0),
            ("FG-BREAD-400", "Classic Sliced Bread 400g", "finished_good", "unit", "1905", 50.0, 15.0, 40.0, 5.0),
        ]

        item_ids = {}
        for it in items_data:
            cur.execute("""
                INSERT OR IGNORE INTO items (sku, name, category, uom, hsn_code, min_stock_alert, standard_cost, selling_price, gst_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, it)
            cur.execute("SELECT id FROM items WHERE sku = ?", (it[0],))
            item_ids[it[0]] = cur.fetchone()["id"]

        # 3. Seed BOM for FG-BREAD-400
        cur.execute("""
            INSERT OR IGNORE INTO boms (bom_code, name, finished_item_id, base_qty, uom, version, description)
            VALUES ('BOM-BREAD-400', 'Standard Recipe: Classic Bread 400g', ?, 1.0, 'unit', 1, 'Standard industrial batch recipe for 400g bread')
        """, (item_ids["FG-BREAD-400"],))
        cur.execute("SELECT id FROM boms WHERE bom_code = 'BOM-BREAD-400'")
        bom_id = cur.fetchone()["id"]

        bom_items_data = [
            (bom_id, item_ids["RM-FLOUR-01"], 0.25, 1.0, "Core wheat flour ingredient"),
            (bom_id, item_ids["RM-SUGAR-01"], 0.03, 0.5, "Sugar sweetness & crust color"),
            (bom_id, item_ids["RM-YEAST-01"], 0.02, 0.5, "Fermentation & leavening agent"),
            (bom_id, item_ids["PM-POUCH-400"], 1.0, 0.5, "Primary packaging pouch"),
        ]
        for bi in bom_items_data:
            cur.execute("""
                INSERT OR IGNORE INTO bom_items (bom_id, component_item_id, quantity, scrap_percentage, notes)
                VALUES (?, ?, ?, ?, ?)
            """, bi)

        # 4. Seed Parties
        parties_data = [
            ("supplier", "Golden Grain Agro Mills Ltd", "29AAGCG1234F1Z8", "080-28391111", "orders@goldengrain.com", "Plot 10, Peenya Industrial Area, Bengaluru", "Karnataka", "29", 0.0, 0.0),
            ("supplier", "Apex Polymer Packagings", "29AAGCA5678B1Z2", "080-28392222", "sales@apexpolymer.com", "Plot 55, Bommasandra Industrial Area, Bengaluru", "Karnataka", "29", 0.0, 0.0),
            ("customer", "Retailer A Supermarkets", "29AABCR9999P1Z1", "080-41235555", "purchase@retailera.com", "Shop 12-14, Commercial Street, Bengaluru", "Karnataka", "29", 50000.0, 0.0),
            ("customer", "Distributor B Wholesale Hub", "29AABCD8888Q1Z4", "0821-2567888", "mgr@distributorb.com", "Sayyaji Rao Road, Mysuru", "Karnataka", "29", 200000.0, 0.0),
        ]
        party_ids = {}
        for p in parties_data:
            cur.execute("""
                INSERT OR IGNORE INTO parties (party_type, name, gstin, phone, email, address, state, state_code, credit_limit, current_balance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, p)
            cur.execute("SELECT id FROM parties WHERE name = ?", (p[1],))
            party_ids[p[1]] = cur.fetchone()["id"]

        today_str = datetime.date.today().isoformat()
        exp_yr = (datetime.date.today() + datetime.timedelta(days=180)).isoformat()

        # Seed Sugar: 100 kg @ ₹42
        record_inward(conn, item_ids["RM-SUGAR-01"], "RM-SUGAR-SEED01", 100.0, 42.0, "opening_stock", 1, today_str, exp_yr, notes="Opening stock", reference_type="SEED")
        # Seed Yeast: 50 kg @ ₹120
        record_inward(conn, item_ids["RM-YEAST-01"], "RM-YEAST-SEED01", 50.0, 120.0, "opening_stock", 1, today_str, exp_yr, notes="Opening stock", reference_type="SEED")
        # Seed Pouches: 2,500 units @ ₹2.50
        record_inward(conn, item_ids["PM-POUCH-400"], "PM-POUCH-SEED01", 2500.0, 2.50, "opening_stock", 1, today_str, exp_yr, notes="Opening stock", reference_type="SEED")
        # Seed 800g Pouches: 1,000 units @ ₹3.80
        record_inward(conn, item_ids["PM-POUCH-800"], "PM-POUCH8-SEED01", 1000.0, 3.80, "opening_stock", 1, today_str, exp_yr, notes="Opening stock", reference_type="SEED")

    print("[SUCCESS] BatchWise database seeded successfully with 5 roles, master BOMs, and parties.")

if __name__ == "__main__":
    seed_database()
