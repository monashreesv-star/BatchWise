import os
import datetime
from pathlib import Path
from app.config import COMPANY, DATA_DIR

INVOICE_PDF_DIR = DATA_DIR / "invoices"
try:
    INVOICE_PDF_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

class GSTInvoiceError(Exception):
    pass

def calculate_gst_breakdown(party_state: str, items: list):
    is_intrastate = (party_state.strip().lower() == COMPANY["state"].strip().lower())
    
    total_taxable = 0.0
    total_cgst = 0.0
    total_sgst = 0.0
    total_igst = 0.0
    
    processed_items = []
    
    for item in items:
        qty = float(item["quantity"])
        unit_price = float(item["unit_price"])
        gst_rate = float(item.get("gst_rate", 5.0))
        hsn_code = str(item.get("hsn_code", "1905"))
        
        taxable = round(qty * unit_price, 2)
        total_taxable += taxable
        
        if is_intrastate:
            half_rate = gst_rate / 2.0
            cgst = round(taxable * (half_rate / 100.0), 2)
            sgst = round(taxable * (half_rate / 100.0), 2)
            igst = 0.0
            item_total = round(taxable + cgst + sgst, 2)
            total_cgst += cgst
            total_sgst += sgst
        else:
            half_rate = 0.0
            cgst = 0.0
            sgst = 0.0
            igst = round(taxable * (gst_rate / 100.0), 2)
            item_total = round(taxable + igst, 2)
            total_igst += igst
            
        processed_items.append({
            "item_id": item["item_id"],
            "sku": item.get("sku", ""),
            "name": item.get("name", ""),
            "batch_id": item.get("batch_id"),
            "batch_number": item.get("batch_number", "N/A"),
            "quantity": qty,
            "unit_price": unit_price,
            "hsn_code": hsn_code,
            "taxable_amount": taxable,
            "gst_rate": gst_rate,
            "cgst_amount": cgst,
            "sgst_amount": sgst,
            "igst_amount": igst,
            "total_amount": item_total
        })
        
    grand_total = round(total_taxable + total_cgst + total_sgst + total_igst, 2)
    
    return {
        "is_intrastate": is_intrastate,
        "items": processed_items,
        "total_taxable": round(total_taxable, 2),
        "total_cgst": round(total_cgst, 2),
        "total_sgst": round(total_sgst, 2),
        "total_igst": round(total_igst, 2),
        "total_tax": round(total_cgst + total_sgst + total_igst, 2),
        "grand_total": grand_total
    }

def number_to_words_inr(num: float) -> str:
    units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
             "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
             "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def convert_upto_999(n):
        res = ""
        if n >= 100:
            res += units[n // 100] + " Hundred "
            n %= 100
        if n >= 20:
            res += tens[n // 10] + (" " + units[n % 10] if n % 10 != 0 else "")
        elif n > 0:
            res += units[n]
        return res.strip()

    num_int = int(num)
    paise = int(round((num - num_int) * 100))

    if num_int == 0:
        return "Zero Rupees Only"

    crores = num_int // 10000000
    num_int %= 10000000
    lakhs = num_int // 100000
    num_int %= 100000
    thousands = num_int // 1000
    remainder = num_int % 1000

    parts = []
    if crores > 0:
        parts.append(convert_upto_999(crores) + " Crore")
    if lakhs > 0:
        parts.append(convert_upto_999(lakhs) + " Lakh")
    if thousands > 0:
        parts.append(convert_upto_999(thousands) + " Thousand")
    if remainder > 0:
        parts.append(convert_upto_999(remainder))

    words = " ".join(parts).strip() + " Rupees"
    if paise > 0:
        words += " and " + convert_upto_999(paise) + " Paise"
    words += " Only"
    return words

def generate_gst_invoice_pdf(invoice_data: dict, output_path: str = None) -> str:
    inv_num = invoice_data["invoice_number"]
    if not output_path:
        output_path = str(INVOICE_PDF_DIR / f"{inv_num}.pdf")

    c_name = COMPANY["name"]
    c_gstin = COMPANY["gstin"]
    c_addr = COMPANY["address"]
    cust = invoice_data["customer"]
    cust_name = cust.get("name", "Valued Customer")
    cust_gstin = cust.get("gstin", "URP")
    cust_addr = cust.get("address", "N/A")
    inv_date = invoice_data["invoice_date"]
    due_date = invoice_data.get("due_date", inv_date)
    so_ref = invoice_data.get("so_number", "N/A")

    stream_lines = []
    def pdf_txt(font, size, x, y, text, color="0 0 0 rg"):
        safe = str(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        return f"BT /{font} {size} Tf {color} {x} {y} Td ({safe}) Tj ET"

    stream_lines.append("q")
    stream_lines.append("0.5 0.5 0.5 RG")
    stream_lines.append("1 w")
    stream_lines.append("30 30 535 780 re S")
    
    stream_lines.append("0.1 0.25 0.5 rg")
    stream_lines.append("30 770 535 40 re f")
    stream_lines.append(pdf_txt("F1", 18, 230, 782, "TAX INVOICE", color="1 1 1 rg"))

    stream_lines.append(pdf_txt("F1", 11, 40, 750, c_name))
    stream_lines.append(pdf_txt("F2", 9, 40, 735, f"GSTIN: {c_gstin} | State: {COMPANY['state']} [{COMPANY['state_code']}]"))
    stream_lines.append(pdf_txt("F2", 8, 40, 722, c_addr[:75]))

    stream_lines.append(pdf_txt("F1", 9, 360, 750, f"Invoice No: {inv_num}"))
    stream_lines.append(pdf_txt("F2", 9, 360, 735, f"Invoice Date: {inv_date}"))
    stream_lines.append(pdf_txt("F2", 9, 360, 722, f"Due Date: {due_date} | SO: {so_ref}"))

    stream_lines.append("0.8 0.8 0.8 RG 30 710 m 565 710 l S")

    stream_lines.append(pdf_txt("F1", 10, 40, 695, "Billed To / Consignee:"))
    stream_lines.append(pdf_txt("F1", 9, 40, 680, cust_name))
    stream_lines.append(pdf_txt("F2", 8, 40, 668, f"GSTIN: {cust_gstin} | State: {cust.get('state', 'Tamil Nadu')}"))
    stream_lines.append(pdf_txt("F2", 8, 40, 656, f"Address: {cust_addr[:70]}"))

    stream_lines.append("0.9 0.92 0.95 rg 30 635 535 18 re f")
    stream_lines.append("0 0 0 RG 30 635 535 18 re S")
    
    stream_lines.append(pdf_txt("F1", 8, 35, 640, "#"))
    stream_lines.append(pdf_txt("F1", 8, 55, 640, "Item Description"))
    stream_lines.append(pdf_txt("F1", 8, 205, 640, "HSN"))
    stream_lines.append(pdf_txt("F1", 8, 245, 640, "Batch"))
    stream_lines.append(pdf_txt("F1", 8, 325, 640, "Qty"))
    stream_lines.append(pdf_txt("F1", 8, 365, 640, "Rate"))
    stream_lines.append(pdf_txt("F1", 8, 415, 640, "Taxable"))
    stream_lines.append(pdf_txt("F1", 8, 475, 640, "GST"))
    stream_lines.append(pdf_txt("F1", 8, 520, 640, "Total"))

    y = 618
    for idx, it in enumerate(invoice_data["items"], start=1):
        desc = it.get("name", it.get("sku", "Item"))[:25]
        hsn = str(it.get("hsn_code", "1905"))
        b_no = str(it.get("batch_number", "N/A"))[:12]
        qty_str = f"{it['quantity']:.0f}"
        rate_str = f"INR {it['unit_price']:.2f}"
        taxable_str = f"{it['taxable_amount']:.2f}"
        gst_pct = f"{it.get('gst_rate', 5.0):.0f}%"
        tot_str = f"{it['total_amount']:.2f}"

        stream_lines.append(pdf_txt("F2", 8, 35, y, str(idx)))
        stream_lines.append(pdf_txt("F2", 8, 55, y, desc))
        stream_lines.append(pdf_txt("F2", 8, 205, y, hsn))
        stream_lines.append(pdf_txt("F2", 8, 245, y, b_no))
        stream_lines.append(pdf_txt("F2", 8, 325, y, qty_str))
        stream_lines.append(pdf_txt("F2", 8, 365, y, rate_str))
        stream_lines.append(pdf_txt("F2", 8, 415, y, taxable_str))
        stream_lines.append(pdf_txt("F2", 8, 475, y, gst_pct))
        stream_lines.append(pdf_txt("F2", 8, 520, y, tot_str))
        y -= 16

    stream_lines.append(f"0.8 0.8 0.8 RG 30 {y} m 565 {y} l S")
    y -= 18
    stream_lines.append(pdf_txt("F2", 9, 350, y, "Taxable Amount:"))
    stream_lines.append(pdf_txt("F2", 9, 480, y, f"INR {invoice_data['total_taxable']:.2f}"))

    if invoice_data.get("total_cgst", 0.0) > 0:
        y -= 14
        stream_lines.append(pdf_txt("F2", 9, 350, y, "Central GST [CGST 2.5%]:"))
        stream_lines.append(pdf_txt("F2", 9, 480, y, f"INR {invoice_data['total_cgst']:.2f}"))
        y -= 14
        stream_lines.append(pdf_txt("F2", 9, 350, y, "State GST [SGST 2.5%]:"))
        stream_lines.append(pdf_txt("F2", 9, 480, y, f"INR {invoice_data['total_sgst']:.2f}"))
    elif invoice_data.get("total_igst", 0.0) > 0:
        y -= 14
        stream_lines.append(pdf_txt("F2", 9, 350, y, "Integrated GST [IGST 5%]:"))
        stream_lines.append(pdf_txt("F2", 9, 480, y, f"INR {invoice_data['total_igst']:.2f}"))

    y -= 16
    stream_lines.append(f"0.1 0.25 0.5 rg 340 {y-3} 225 18 re f")
    stream_lines.append(pdf_txt("F1", 10, 350, y+2, "Grand Total [INR]:", color="1 1 1 rg"))
    stream_lines.append(pdf_txt("F1", 10, 480, y+2, f"INR {invoice_data['grand_total']:.2f}", color="1 1 1 rg"))

    y -= 25
    words = number_to_words_inr(invoice_data["grand_total"])
    stream_lines.append(pdf_txt("F1", 8, 40, y, "Amount Chargeable in Words:"))
    stream_lines.append(pdf_txt("F2", 8, 40, y-12, words[:80]))

    y_footer = 75
    stream_lines.append(f"0.8 0.8 0.8 RG 30 {y_footer+45} m 565 {y_footer+45} l S")
    stream_lines.append(pdf_txt("F1", 8, 40, y_footer+30, "Bank Details for NEFT/RTGS:"))
    stream_lines.append(pdf_txt("F2", 8, 40, y_footer+18, "Bank: HDFC Bank | A/C: 50200048192841 | IFSC: HDFC0001248"))
    stream_lines.append(pdf_txt("F2", 7, 40, y_footer+6, "Declaration: Goods once sold will not be taken back or exchanged."))

    stream_lines.append(pdf_txt("F1", 8, 380, y_footer+30, f"For {c_name}"))
    stream_lines.append(pdf_txt("F2", 7, 440, y_footer+6, "Authorized Signatory"))
    stream_lines.append(f"0.5 0.5 0.5 RG 380 {y_footer+15} 170 0.5 re S")

    stream_lines.append("Q")

    content_stream = "\n".join(stream_lines).encode("latin-1")
    stream_len = len(content_stream)

    pdf_parts = []
    pdf_parts.append(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    
    def add_object(obj_bytes):
        offsets.append(sum(len(p) for p in pdf_parts))
        pdf_parts.append(obj_bytes)

    add_object(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    add_object(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
    add_object(b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] /Contents 4 0 R /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>\nendobj\n")
    add_object(f"4 0 obj\n<< /Length {stream_len} >>\nstream\n".encode("latin-1") + content_stream + b"\nendstream\nendobj\n")
    add_object(b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n")
    add_object(b"6 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")

    xref_offset = sum(len(p) for p in pdf_parts)
    pdf_parts.append(f"xref\n0 {len(offsets)+1}\n0000000000 65535 f \n".encode("latin-1"))
    for off in offsets:
        pdf_parts.append(f"{off:010d} 00000 n \n".encode("latin-1"))

    pdf_parts.append(f"trailer\n<< /Size {len(offsets)+1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("latin-1"))

    full_pdf = b"".join(pdf_parts)
    with open(output_path, "wb") as f:
        f.write(full_pdf)

    return output_path
