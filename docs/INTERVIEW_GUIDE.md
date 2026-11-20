# BatchWise ERP - Technical Interview & Live Code Modification Guide

---

## 1. Interview Preparation Overview

In competitive technical internship interviews, evaluators focus on **code ownership** and your ability to modify the codebase live under pressure. This guide prepares you for the live code walkthrough and the anticipated on-the-spot modification challenge: **adding another pack size sharing an existing BOM**.

---

## 2. On-The-Spot Modification Challenge: Adding a New Pack Size

### The Challenge
> *"Suppose marketing wants to introduce a new **Family Pack 800g** SKU. It must use the exact same bread dough formula as the existing 400g bread, but double the dough ingredients and use an 800g pouch (`PM-POUCH-800`). How do you implement this without duplicating the dough recipe?"*

### The Solution Architecture
In `app/engine/bom_production.py`, BatchWise provides `add_pack_size_bom()`:

```python
def add_pack_size_bom(conn, base_bom_code: str, new_sku: str, new_name: str,
                      multiplier: float, new_packing_item_id: int, selling_price: float):
    """
    1. Reads the base recipe from base_bom_code ('BOM-BREAD-400').
    2. Creates the new finished SKU ('FG-BREAD-800').
    3. Creates a new BOM header linked to the new SKU.
    4. Copies component items:
       - If category == 'packing_material', substitutes new_packing_item_id (800g pouch).
       - If category == 'raw_material', scales quantity by multiplier (2.0x).
    """
```

### Live Python Walkthrough in REPL / Shell
To demonstrate this live in front of the evaluator:
```bash
python -c "
from app.database import get_db
from app.engine.bom_production import add_pack_size_bom, calculate_bom_requirements

with get_db() as conn:
    item_id, bom_id = add_pack_size_bom(
        conn,
        base_bom_code='BOM-BREAD-400',
        new_sku='FG-BREAD-800',
        new_name='Family Sliced Bread 800g',
        multiplier=2.0,
        new_packing_item_id=5,
        selling_price=75.0
    )
    calc = calculate_bom_requirements(conn, bom_id, target_qty=10.0)
    for c in calc['components']:
        print(f'{c[\"component_name\"]}: {c[\"standard_qty\"]} {c[\"component_uom\"]}')
"
```
**Expected Output:**
```
Refined Wheat Flour Grade A: 5.05 kg (0.50 kg/unit + 1% scrap)
Refined Cane Sugar: 0.603 kg
Active Baker's Yeast & Salt Premix: 0.402 kg
Food-Grade Family Bread Pouch 800g: 10.05 units
```

---

## 3. Explaining Key Architectural Functions

### A. Double-Entry Stock Ledger (`app/engine/ledger.py`)
* **`record_inward(...)`**: Creates or increments a specific batch lot (`stock_batches`) and writes an immutable audit record to `stock_transactions` with `transaction_type = 'INWARD'` or `'PRODUCTION_IN'`.
* **`record_outward(...)`**: Validates sufficient stock in the specified lot (preventing negative balances), decrements `stock_batches.current_qty`, and writes an immutable negative ledger record.
* **`allocate_stock_fifo(...)`**: Implements First-In-First-Out (FIFO) dispatch. Queries active batches sorted by `mfg_date ASC, id ASC`, fulfilling the requested quantity across batches.
* **`verify_inventory_integrity(...)`**: Audits that $\sum \text{stock\_transactions.qty} == \sum \text{stock\_batches.current\_qty}$.

### B. Variance Analysis & Costing (`app/engine/bom_production.py`)
* **`calculate_bom_requirements(...)`**: Scales BOM standard ingredients to target production size, including scrap allowances.
* **`execute_production_run(...)`**:
  1. Deducts consumed raw materials from inventory.
  2. Calculates **Material Quantity Variance (MQV)**: $(\text{Std Qty for Actual Output} - \text{Actual Qty Consumed}) \times \text{Std Cost}$.
  3. Calculates **Yield Variance**: $[(\text{Actual Output} - \text{Target}) / \text{Target}] \times 100\%$.
  4. Computes **True Unit Cost**: $(\sum \text{Actual Material Costs} + \text{Labor} + \text{Overhead}) / \text{Actual Output}$.
  5. Inwards finished good batch with the computed unit cost basis.

### C. Shortage Detection Engine (`app/engine/shortage.py`)
* **`check_stock_shortage(...)`**: Compares order demand against active inventory. For deficit quantities, it traverses the active BOM to compute exact raw material replenishment quantities and purchase cost estimates before order commitment.
