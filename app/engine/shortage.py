from app.engine.ledger import get_item_stock
from app.engine.bom_production import calculate_bom_requirements

def check_stock_shortage(conn, items_requested: list):
    cur = conn.cursor()
    shortage_details = []
    has_shortage = False
    replenishment_requirements = []

    for req in items_requested:
        item_id = req["item_id"]
        req_qty = float(req["quantity"])

        cur.execute("SELECT id, sku, name, uom, category, selling_price FROM items WHERE id = ?", (item_id,))
        item = cur.fetchone()
        if not item:
            continue

        avail_stock = get_item_stock(conn, item_id)
        shortage_qty = round(max(0.0, req_qty - avail_stock), 4)

        item_status = {
            "item_id": item_id,
            "sku": item["sku"],
            "name": item["name"],
            "uom": item["uom"],
            "requested_qty": req_qty,
            "available_stock": avail_stock,
            "shortage_qty": shortage_qty,
            "is_shortage": shortage_qty > 0,
            "fulfillment_percentage": round((min(avail_stock, req_qty) / req_qty) * 100.0, 1) if req_qty > 0 else 100.0
        }

        if shortage_qty > 0:
            has_shortage = True
            cur.execute("SELECT id FROM boms WHERE finished_item_id = ? AND is_active = 1 LIMIT 1", (item_id,))
            bom = cur.fetchone()
            if bom:
                bom_calc = calculate_bom_requirements(conn, bom["id"], shortage_qty)
                for comp in bom_calc["components"]:
                    rm_avail = get_item_stock(conn, comp["component_item_id"])
                    rm_req = comp["standard_qty"]
                    rm_shortage = round(max(0.0, rm_req - rm_avail), 4)

                    replenishment_requirements.append({
                        "finished_item_sku": item["sku"],
                        "component_item_id": comp["component_item_id"],
                        "component_sku": comp["component_sku"],
                        "component_name": comp["component_name"],
                        "component_uom": comp["component_uom"],
                        "required_for_production": rm_req,
                        "raw_material_in_stock": rm_avail,
                        "raw_material_shortage": rm_shortage,
                        "unit_cost": comp["unit_cost"],
                        "estimated_purchase_cost": round(rm_shortage * comp["unit_cost"], 2)
                    })

        shortage_details.append(item_status)

    return {
        "has_shortage": has_shortage,
        "items": shortage_details,
        "raw_material_replenishment": replenishment_requirements,
        "summary": "SHORTAGE DETECTED: Stock deficit requires production replenishment." if has_shortage else "STOCK SUFFICIENT: All order items available in active inventory."
    }
