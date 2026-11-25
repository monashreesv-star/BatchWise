import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import get_db
from seed import seed_database
from app.engine.bom_production import calculate_bom_requirements, add_pack_size_bom

class TestBOMVariance(unittest.TestCase):
    def setUp(self):
        seed_database(clean=True)

    def test_bom_requirement_calculation(self):
        with get_db() as conn:
            calc = calculate_bom_requirements(conn, bom_id=1, target_qty=100.0)
            self.assertEqual(calc["target_qty"], 100.0)
            comp_map = {c["component_sku"]: c for c in calc["components"]}

            self.assertAlmostEqual(comp_map["RM-FLOUR-01"]["standard_qty"], 20.0, places=2)
            self.assertAlmostEqual(comp_map["PM-POUCH-200"]["standard_qty"], 100.0, places=1)

    def test_dynamic_multi_pack_extension(self):
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM items WHERE sku = 'PM-POUCH-400'")
            pouch_400_id = cur.fetchone()["id"]

            new_item_id, new_bom_id = add_pack_size_bom(
                conn, base_bom_code="BOM-MURUKKU-200", new_sku="FG-MURUKKU-400",
                new_name="Murukku Family Pack 400g", multiplier=2.0,
                new_packing_item_id=pouch_400_id, selling_price=95.0
            )

            calc_400 = calculate_bom_requirements(conn, bom_id=new_bom_id, target_qty=10.0)
            comp_map = {c["component_sku"]: c for c in calc_400["components"]}

            self.assertAlmostEqual(comp_map["RM-FLOUR-01"]["standard_qty"], 4.0, places=2)
            self.assertIn("PM-POUCH-400", comp_map)

if __name__ == "__main__":
    unittest.main()
