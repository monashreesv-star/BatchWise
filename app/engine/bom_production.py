import datetime
from app.engine.ledger import record_inward, record_outward, get_item_stock, LedgerError

class ProductionError(Exception):
    pass

def calculate_bom_requirements(conn, bom_id: int, target_qty: float):
    cur = conn.cursor()
    cur.execute("""
        SELECT b.*, i.name as finished_item_name, i.sku as finished_item_sku, i.standard_cost
        FROM boms b
        JOIN items i ON b.finished_item_id = i.id
        WHERE b.id = ?
    """, (bom_id,))
    bom = cur.fetchone()
    if not bom:
        raise ProductionError(f"BOM with ID {bom_id} not found.")

    cur.execute("""
        SELECT bi.*, i.name as component_name, i.sku as component_sku, i.uom as component_uom,
               i.standard_cost as component_cost, i.category
        FROM bom_items bi
        JOIN items i ON bi.component_item_id = i.id
        WHERE bi.bom_id = ?
    """, (bom_id,))
    items = cur.fetchall()

    scale = target_qty / bom["base_qty"]
    components = []
    total_std_cost = 0.0

    for item in items:
        base_req = round(item["quantity"] * scale, 4)
        scrap_allowance = round(base_req * (item["scrap_percentage"] / 100.0), 4)
        total_std_req = round(base_req + scrap_allowance, 4)
        est_cost = round(total_std_req * item["component_cost"], 2)
        total_std_cost += est_cost

        components.append({
            "component_item_id": item["component_item_id"],
            "component_sku": item["component_sku"],
            "component_name": item["component_name"],
            "component_uom": item["component_uom"],
            "category": item["category"],
            "unit_quantity": item["quantity"],
            "base_required": base_req,
            "scrap_percentage": item["scrap_percentage"],
            "standard_qty": total_std_req,
            "unit_cost": item["component_cost"],
            "estimated_cost": est_cost
        })

    return {
        "bom": bom,
        "target_qty": target_qty,
        "components": components,
        "total_standard_material_cost": round(total_std_cost, 2),
        "standard_unit_material_cost": round(total_std_cost / target_qty, 2) if target_qty > 0 else 0.0
    }

def create_work_order(conn, bom_id: int, target_qty: float, batch_number: str,
                      start_date: str, created_by: int = None, notes: str = None):
    calc = calculate_bom_requirements(conn, bom_id, target_qty)
    bom = calc["bom"]

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as count FROM production_work_orders")
    wo_count = cur.fetchone()["count"] + 1
    wo_number = f"WO-{datetime.date.today().strftime('%Y%m%d')}-{wo_count:04d}"

    cur.execute("""
        INSERT INTO production_work_orders (
            wo_number, bom_id, finished_item_id, batch_number, target_qty,
            status, start_date, standard_material_cost, notes, created_by
        ) VALUES (?, ?, ?, ?, ?, 'planned', ?, ?, ?, ?)
    """, (
        wo_number, bom_id, bom["finished_item_id"], batch_number, target_qty,
        start_date, calc["total_standard_material_cost"], notes, created_by
    ))
    return cur.lastrowid

def execute_production_run(conn, wo_id: int, actual_qty_produced: float,
                           consumptions: list, labor_cost: float = 0.0,
                           overhead_cost: float = 0.0, completion_date: str = None,
                           created_by: int = None, mfg_date: str = None, expiry_date: str = None):
    cur = conn.cursor()
    cur.execute("""
        SELECT wo.*, b.base_qty, i.standard_cost, i.sku as finished_sku
        FROM production_work_orders wo
        JOIN boms b ON wo.bom_id = b.id
        JOIN items i ON wo.finished_item_id = i.id
        WHERE wo.id = ?
    """, (wo_id,))
    wo = cur.fetchone()
    if not wo:
        raise ProductionError(f"Work order {wo_id} does not exist.")
    if wo["status"] == "completed":
        raise ProductionError(f"Work order {wo['wo_number']} is already completed.")

    if actual_qty_produced <= 0:
        raise ProductionError("Actual quantity produced must be greater than zero.")

    completion_date = completion_date or datetime.date.today().isoformat()
    mfg_date = mfg_date or completion_date
    if not expiry_date:
        exp_dt = datetime.date.fromisoformat(mfg_date) + datetime.timedelta(days=7)
        expiry_date = exp_dt.isoformat()

    cur.execute("SELECT * FROM bom_items WHERE bom_id = ?", (wo["bom_id"],))
    bom_items = {b["component_item_id"]: b for b in cur.fetchall()}

    total_actual_material_cost = 0.0
    total_mqv = 0.0
    total_scrap_qty = 0.0

    for c in consumptions:
        comp_id = c["component_item_id"]
        batch_id = c["batch_id"]
        act_qty = float(c["actual_qty"])
        scrap_qty = float(c.get("scrap_qty", 0.0))
        c_notes = c.get("notes", "")

        cur.execute("SELECT * FROM stock_batches WHERE id = ?", (batch_id,))
        batch = cur.fetchone()
        if not batch:
            raise ProductionError(f"Stock batch {batch_id} not found.")

        unit_cost = batch["unit_cost"]
        mat_cost = round(act_qty * unit_cost, 2)
        total_actual_material_cost += mat_cost
        total_scrap_qty += scrap_qty

        bom_line = bom_items.get(comp_id)
        if bom_line:
            std_ratio = bom_line["quantity"] / wo["base_qty"]
            std_qty_for_output = round(std_ratio * actual_qty_produced, 4)
        else:
            std_qty_for_output = act_qty

        var_qty = round(std_qty_for_output - act_qty, 4)
        mqv = round(var_qty * unit_cost, 2)
        total_mqv += mqv

        record_outward(
            conn, item_id=comp_id, batch_id=batch_id, qty=act_qty,
            reference_type="WO", reference_id=wo_id, created_by=created_by,
            notes=f"Consumed in {wo['wo_number']}", transaction_type="PRODUCTION_OUT"
        )

        cur.execute("""
            INSERT INTO wo_material_consumptions (
                wo_id, component_item_id, batch_id, batch_number, standard_qty,
                actual_qty, variance_qty, unit_cost, variance_cost, scrap_qty, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            wo_id, comp_id, batch_id, batch["batch_number"], std_qty_for_output,
            act_qty, var_qty, unit_cost, mqv, scrap_qty, c_notes
        ))

    total_actual_cost = round(total_actual_material_cost + labor_cost + overhead_cost, 2)
    actual_unit_cost = round(total_actual_cost / actual_qty_produced, 4)
    yield_var_pct = round(((actual_qty_produced - wo["target_qty"]) / wo["target_qty"]) * 100.0, 2)
    scrap_finished = round(wo["target_qty"] - actual_qty_produced, 4) if wo["target_qty"] > actual_qty_produced else 0.0

    record_inward(
        conn, item_id=wo["finished_item_id"], batch_number=wo["batch_number"],
        qty=actual_qty_produced, unit_cost=actual_unit_cost, source_type="production",
        source_id=wo_id, mfg_date=mfg_date, expiry_date=expiry_date,
        created_by=created_by, notes=f"Finished goods from {wo['wo_number']}",
        reference_type="WO"
    )

    cur.execute("""
        UPDATE production_work_orders
        SET actual_qty = ?, scrap_qty = ?, status = 'completed',
            completion_date = ?, actual_material_cost = ?, labor_cost = ?,
            overhead_cost = ?, total_actual_cost = ?, actual_unit_cost = ?,
            material_quantity_variance = ?, yield_variance_percentage = ?
        WHERE id = ?
    """, (
        actual_qty_produced, scrap_finished, completion_date,
        round(total_actual_material_cost, 2), round(labor_cost, 2),
        round(overhead_cost, 2), total_actual_cost, actual_unit_cost,
        round(total_mqv, 2), yield_var_pct, wo_id
    ))

    return {
        "wo_id": wo_id,
        "wo_number": wo["wo_number"],
        "batch_number": wo["batch_number"],
        "actual_qty_produced": actual_qty_produced,
        "total_actual_material_cost": round(total_actual_material_cost, 2),
        "total_actual_cost": total_actual_cost,
        "actual_unit_cost": actual_unit_cost,
        "material_quantity_variance": round(total_mqv, 2),
        "yield_variance_percentage": yield_var_pct,
        "scrap_finished_units": scrap_finished
    }

def add_pack_size_bom(conn, base_bom_code: str, new_sku: str, new_name: str,
                      multiplier: float, new_packing_item_id: int, selling_price: float):
    cur = conn.cursor()
    cur.execute("SELECT * FROM boms WHERE bom_code = ?", (base_bom_code,))
    base_bom = cur.fetchone()
    if not base_bom:
        raise ProductionError(f"Base BOM {base_bom_code} not found.")

    cur.execute("""
        INSERT INTO items (sku, name, category, uom, hsn_code, min_stock_alert, standard_cost, selling_price, gst_rate)
        VALUES (?, ?, 'finished_good', 'unit', '1905', 50.0, ?, ?, 5.0)
    """, (new_sku, new_name, round(base_bom["base_qty"] * multiplier * 15.0, 2), selling_price))
    new_item_id = cur.lastrowid

    new_bom_code = f"BOM-{new_sku}"
    cur.execute("""
        INSERT INTO boms (bom_code, name, finished_item_id, base_qty, uom, version, description)
        VALUES (?, ?, ?, ?, 'unit', 1, ?)
    """, (new_bom_code, f"Recipe for {new_name}", new_item_id, base_bom["base_qty"], f"Derived from {base_bom_code} (scale {multiplier}x)"))
    new_bom_id = cur.lastrowid

    cur.execute("""
        SELECT bi.*, i.category
        FROM bom_items bi
        JOIN items i ON bi.component_item_id = i.id
        WHERE bi.bom_id = ?
    """, (base_bom["id"],))
    base_items = cur.fetchall()

    added_components = set()
    for bi in base_items:
        if bi["category"] == "packing_material":
            if new_packing_item_id not in added_components:
                cur.execute("""
                    INSERT INTO bom_items (bom_id, component_item_id, quantity, scrap_percentage, notes)
                    VALUES (?, ?, ?, ?, 'Specific packaging for new pack size')
                """, (new_bom_id, new_packing_item_id, bi["quantity"], bi["scrap_percentage"]))
                added_components.add(new_packing_item_id)
            elif bi["component_item_id"] not in added_components:
                cur.execute("""
                    INSERT INTO bom_items (bom_id, component_item_id, quantity, scrap_percentage, notes)
                    VALUES (?, ?, ?, ?, 'Secondary packaging for new pack size')
                """, (new_bom_id, bi["component_item_id"], bi["quantity"], bi["scrap_percentage"]))
                added_components.add(bi["component_item_id"])
        else:
            scaled_qty = round(bi["quantity"] * multiplier, 4)
            if bi["component_item_id"] not in added_components:
                cur.execute("""
                    INSERT INTO bom_items (bom_id, component_item_id, quantity, scrap_percentage, notes)
                    VALUES (?, ?, ?, ?, 'Scaled from core recipe')
                """, (new_bom_id, bi["component_item_id"], scaled_qty, bi["scrap_percentage"]))
                added_components.add(bi["component_item_id"])

    return new_item_id, new_bom_id
