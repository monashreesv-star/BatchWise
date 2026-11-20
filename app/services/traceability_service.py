from app.database import get_db

def trace_finished_good_upstream(conn, batch_number: str):
    cur = conn.cursor()
    cur.execute("""
        SELECT sb.*, i.sku, i.name as item_name, i.category, wo.id as wo_id,
               wo.wo_number, wo.target_qty, wo.actual_qty, wo.actual_unit_cost,
               wo.start_date, wo.completion_date, b.bom_code, b.name as bom_name
        FROM stock_batches sb
        JOIN items i ON sb.item_id = i.id
        LEFT JOIN production_work_orders wo ON sb.source_id = wo.id AND sb.source_type = 'production'
        LEFT JOIN boms b ON wo.bom_id = b.id
        WHERE sb.batch_number = ?
    """, (batch_number,))
    fg_batch = cur.fetchone()

    if not fg_batch:
        return {"found": False, "message": f"Batch '{batch_number}' not found."}

    consumed_materials = []
    if fg_batch["wo_id"]:
        cur.execute("""
            SELECT wmc.*, i.sku as comp_sku, i.name as comp_name, i.uom as comp_uom,
                   grn.id as grn_id, grn.grn_number, grn.receipt_date,
                   po.id as po_id, po.po_number, p.name as supplier_name, p.gstin as supplier_gstin
            FROM wo_material_consumptions wmc
            JOIN items i ON wmc.component_item_id = i.id
            LEFT JOIN stock_batches rmb ON wmc.batch_id = rmb.id
            LEFT JOIN goods_receipt_notes grn ON rmb.source_id = grn.id AND rmb.source_type = 'grn'
            LEFT JOIN purchase_orders po ON grn.po_id = po.id
            LEFT JOIN parties p ON po.supplier_id = p.id
            WHERE wmc.wo_id = ?
        """, (fg_batch["wo_id"],))
        consumed_materials = cur.fetchall()

    return {
        "found": True,
        "batch_type": "finished_good",
        "batch_details": fg_batch,
        "raw_materials_consumed": consumed_materials
    }

def trace_raw_material_downstream(conn, batch_number: str):
    cur = conn.cursor()
    cur.execute("""
        SELECT sb.*, i.sku, i.name as item_name, grn.grn_number, grn.receipt_date,
               po.po_number, sup.name as supplier_name
        FROM stock_batches sb
        JOIN items i ON sb.item_id = i.id
        LEFT JOIN goods_receipt_notes grn ON sb.source_id = grn.id AND sb.source_type = 'grn'
        LEFT JOIN purchase_orders po ON grn.po_id = po.id
        LEFT JOIN parties sup ON po.supplier_id = sup.id
        WHERE sb.batch_number = ?
    """, (batch_number,))
    rm_batch = cur.fetchone()

    if not rm_batch:
        return {"found": False, "message": f"Raw material batch '{batch_number}' not found."}

    cur.execute("""
        SELECT DISTINCT wo.id as wo_id, wo.wo_number, wo.batch_number as fg_batch_number,
               wo.actual_qty, wo.completion_date, i.sku as fg_sku, i.name as fg_name
        FROM wo_material_consumptions wmc
        JOIN production_work_orders wo ON wmc.wo_id = wo.id
        JOIN items i ON wo.finished_item_id = i.id
        WHERE wmc.batch_number = ? OR wmc.batch_id = ?
    """, (batch_number, rm_batch["id"]))
    work_orders = cur.fetchall()

    dispatches = []
    fg_batch_numbers = [wo["fg_batch_number"] for wo in work_orders]

    if fg_batch_numbers:
        placeholders = ",".join("?" * len(fg_batch_numbers))
        cur.execute(f"""
            SELECT DISTINCT ii.batch_number, ii.quantity, ii.unit_price,
                   inv.invoice_number, inv.invoice_date, cust.id as customer_id,
                   cust.name as customer_name, cust.phone as customer_phone, cust.email as customer_email
            FROM invoice_items ii
            JOIN invoices inv ON ii.invoice_id = inv.id
            JOIN parties cust ON inv.customer_id = cust.id
            WHERE ii.batch_number IN ({placeholders})
        """, tuple(fg_batch_numbers))
        dispatches = cur.fetchall()

    return {
        "found": True,
        "batch_type": "raw_material",
        "batch_details": rm_batch,
        "work_orders_used_in": work_orders,
        "customers_dispatched_to": dispatches,
        "total_customers_affected": len(set(d["customer_id"] for d in dispatches))
    }
