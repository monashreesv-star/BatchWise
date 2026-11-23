import csv
import io
import datetime
from app.database import get_db

def get_monthly_stock_ledger_summary(conn, month_str: str = None):
    month_str = month_str or datetime.date.today().strftime("%Y-%m")
    start_date = f"{month_str}-01"

    cur = conn.cursor()
    cur.execute("""
        SELECT i.id, i.sku, i.name, i.uom, i.category, i.standard_cost,
               COALESCE(SUM(CASE WHEN st.created_at < ? THEN st.qty ELSE 0 END), 0.0) as opening_qty,
               COALESCE(SUM(CASE WHEN st.created_at >= ? AND st.qty > 0 THEN st.qty ELSE 0 END), 0.0) as inward_qty,
               COALESCE(SUM(CASE WHEN st.created_at >= ? AND st.qty < 0 THEN ABS(st.qty) ELSE 0 END), 0.0) as outward_qty,
               COALESCE(SUM(st.qty), 0.0) as closing_qty
        FROM items i
        LEFT JOIN stock_transactions st ON i.id = st.item_id
        GROUP BY i.id
        ORDER BY i.category, i.sku
    """, (start_date, start_date, start_date))
    rows = cur.fetchall()

    summary = []
    total_inventory_value = 0.0

    for r in rows:
        val = round(r["closing_qty"] * r["standard_cost"], 2)
        total_inventory_value += val
        summary.append({
            "item_id": r["id"],
            "sku": r["sku"],
            "name": r["name"],
            "uom": r["uom"],
            "category": r["category"],
            "opening_qty": round(r["opening_qty"], 2),
            "inward_qty": round(r["inward_qty"], 2),
            "outward_qty": round(r["outward_qty"], 2),
            "closing_qty": round(r["closing_qty"], 2),
            "standard_cost": r["standard_cost"],
            "total_valuation": val
        })

    return {
        "month": month_str,
        "items": summary,
        "item_list": summary,
        "total_inventory_value": round(total_inventory_value, 2)
    }

def get_gstr1_sales_report(conn, month_str: str = None):
    month_str = month_str or datetime.date.today().strftime("%Y-%m")
    cur = conn.cursor()
    cur.execute("""
        SELECT inv.invoice_number, inv.invoice_date, p.name as customer_name,
               COALESCE(p.gstin, 'URP') as customer_gstin, p.state as place_of_supply,
               inv.total_taxable, inv.total_cgst, inv.total_sgst, inv.total_igst,
               inv.grand_total, inv.status
        FROM invoices inv
        JOIN parties p ON inv.customer_id = p.id
        WHERE strftime('%Y-%m', inv.invoice_date) = ?
        ORDER BY inv.invoice_date ASC
    """, (month_str,))
    invoices = cur.fetchall()

    totals = {
        "total_taxable": round(sum(i["total_taxable"] for i in invoices), 2),
        "total_cgst": round(sum(i["total_cgst"] for i in invoices), 2),
        "total_sgst": round(sum(i["total_sgst"] for i in invoices), 2),
        "total_igst": round(sum(i["total_igst"] for i in invoices), 2),
        "grand_total": round(sum(i["grand_total"] for i in invoices), 2)
    }
    return {"month": month_str, "invoices": invoices, "totals": totals}

def get_production_variance_report(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT wo.id, wo.wo_number, wo.batch_number, i.sku, i.name as finished_good_name,
               wo.target_qty, wo.actual_qty, wo.scrap_qty, wo.start_date, wo.completion_date,
               wo.standard_material_cost, wo.actual_material_cost, wo.total_actual_cost,
               wo.actual_unit_cost, wo.material_quantity_variance, wo.yield_variance_percentage,
               wo.status
        FROM production_work_orders wo
        JOIN items i ON wo.finished_item_id = i.id
        ORDER BY wo.id DESC
    """)
    orders = cur.fetchall()
    return {"work_orders": orders}

def export_to_csv(data: list, headers: list, field_names: list) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in data:
        writer.writerow([row.get(f, "") for f in field_names])
    return output.getvalue()

def export_to_excel_xml(title: str, headers: list, data: list, field_names: list) -> str:
    xml = ['<?xml version="1.0"?>']
    xml.append('<?mso-application progid="Excel.Sheet"?>')
    xml.append('<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"')
    xml.append(' xmlns:o="urn:schemas-microsoft-com:office:office"')
    xml.append(' xmlns:x="urn:schemas-microsoft-com:office:excel"')
    xml.append(' xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">')
    
    xml.append('<Styles>')
    xml.append('<Style ss:ID="Default" ss:Name="Normal"><Alignment ss:Vertical="Bottom"/></Style>')
    xml.append('<Style ss:ID="HeaderStyle"><Font ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#1E3A8A" ss:Pattern="Solid"/><Alignment ss:Horizontal="Center"/></Style>')
    xml.append('<Style ss:ID="TitleStyle"><Font ss:Bold="1" ss:Size="14" ss:Color="#1E3A8A"/></Style>')
    xml.append('<Style ss:ID="NumberStyle"><NumberFormat ss:Format="#,##0.00"/></Style>')
    xml.append('</Styles>')

    xml.append(f'<Worksheet ss:Name="{title[:31]}">')
    xml.append('<Table>')

    xml.append(f'<Row><Cell ss:StyleID="TitleStyle"><Data ss:Type="String">{title} - BatchWise ERP</Data></Cell></Row>')
    xml.append('<Row/>')

    xml.append('<Row>')
    for h in headers:
        xml.append(f'<Cell ss:StyleID="HeaderStyle"><Data ss:Type="String">{h}</Data></Cell>')
    xml.append('</Row>')

    for row in data:
        xml.append('<Row>')
        for f in field_names:
            val = row.get(f, "")
            if isinstance(val, (int, float)):
                xml.append(f'<Cell ss:StyleID="NumberStyle"><Data ss:Type="Number">{val}</Data></Cell>')
            else:
                xml.append(f'<Cell><Data ss:Type="String">{str(val)}</Data></Cell>')
        xml.append('</Row>')

    xml.append('</Table>')
    xml.append('</Worksheet>')
    xml.append('</Workbook>')
    return "\n".join(xml)
