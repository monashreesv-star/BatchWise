import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.gst_invoice import calculate_gst_breakdown, number_to_words_inr, generate_gst_invoice_pdf

class TestGSTInvoice(unittest.TestCase):
    def test_intrastate_gst(self):
        items = [{"item_id": 1, "quantity": 100, "unit_price": 40.0, "gst_rate": 5.0}]
        res = calculate_gst_breakdown("Tamil Nadu", items)
        self.assertTrue(res["is_intrastate"])
        self.assertEqual(res["total_taxable"], 4000.0)
        self.assertEqual(res["total_cgst"], 100.0)
        self.assertEqual(res["total_sgst"], 100.0)
        self.assertEqual(res["total_igst"], 0.0)
        self.assertEqual(res["grand_total"], 4200.0)

    def test_interstate_gst(self):
        items = [{"item_id": 1, "quantity": 100, "unit_price": 40.0, "gst_rate": 5.0}]
        res = calculate_gst_breakdown("Karnataka", items)
        self.assertFalse(res["is_intrastate"])
        self.assertEqual(res["total_taxable"], 4000.0)
        self.assertEqual(res["total_cgst"], 0.0)
        self.assertEqual(res["total_sgst"], 0.0)
        self.assertEqual(res["total_igst"], 200.0)
        self.assertEqual(res["grand_total"], 4200.0)

    def test_number_to_words(self):
        words = number_to_words_inr(4200.0)
        self.assertEqual(words, "Four Thousand Two Hundred Rupees Only")
        words2 = number_to_words_inr(15500.50)
        self.assertEqual(words2, "Fifteen Thousand Five Hundred Rupees and Fifty Paise Only")

if __name__ == "__main__":
    unittest.main()
