# BatchWise ERP - Technical Design Note (Two-Page Architectural Specification)

---

## 1. System Architecture & Engineering Philosophy

**BatchWise** is an industrial-grade enterprise resource planning and manufacturing execution system tailored for batch-controlled FMCG and food manufacturing. Standard transactional applications often focus exclusively on billing; BatchWise treats the **manufacturing calculation engine**, **immutable stock ledger**, and **end-to-end traceability** as primary first-class systems.

```
+-----------------------------------------------------------------------------------+
|                                Client Presentation                                |
|           Responsive Web UI (Jinja2 / Bootstrap 5) + RESTful JSON APIs           |
+-----------------------------------------------------------------------------------+
                                         |
+-----------------------------------------------------------------------------------+
|                        Security & Governance (RBAC Layer)                         |
|   5 Business Personas: Admin | Salesman | Purchase Mgr | Production Mgr | Auditor |
|   PBKDF2-SHA256 Password Cryptography + Signed HMAC Session Token Authentication  |
+-----------------------------------------------------------------------------------+
                                         |
+-----------------------------------------------------------------------------------+
|                               Core Business Engines                               |
|   1. Double-Entry Stock Ledger Engine (FIFO Lot Allocation & Integrity Invariants)|
|   2. Production & BOM Variance Engine (Standard Costing, MQV, Scrap & Unit Cost)  |
|   3. Shortage Detection & Replenishment Intelligence Engine                       |
|   4. Statutory GST Tax Calculation & Native PDF Generation Engine                 |
|   5. 360° Traceability Matrix Engine (Upstream Genealogy & Downstream Recall)     |
+-----------------------------------------------------------------------------------+
                                         |
+-----------------------------------------------------------------------------------+
|                             Storage & Persistence Layer                           |
|       SQLite 3 with Write-Ahead Logging (WAL), Strict Foreign Key Constraints,    |
|               CHECK Invariants, and Transactional Isolation Safeguards            |
+-----------------------------------------------------------------------------------+
```

---

## 2. Immutable Double-Entry Stock Ledger

Many ERP systems suffer from inventory corruption because they perform destructive updates (e.g., `UPDATE items SET stock = stock - X`). In BatchWise, inventory is maintained using a **double-entry, audit-verifiable ledger pattern**:

1. **Physical Lot Segregation (`stock_batches`)**: Every inward receipt (GRN) or production output generates a distinct lot record with manufacturing date, expiry date, source document link, and unit cost.
2. **Immutable Ledger Transactions (`stock_transactions`)**:
   - Stock increases (`INWARD`, `PRODUCTION_IN`) are recorded with positive quantities and positive valuations.
   - Stock deductions (`OUTWARD`, `PRODUCTION_OUT`, `SCRAP`) are recorded with negative quantities and negative valuations.
3. **Continuous Reconciliation Invariant**:
   $$\sum \text{qty in } \texttt{stock\_transactions} \equiv \sum \text{current\_qty in } \texttt{stock\_batches}$$
   The system provides an automated audit assertion `verify_inventory_integrity()` that flags any drift between aggregated transactions and active lots down to $0.0001$ tolerance.
4. **FIFO Allocation**: During sales dispatch, the allocation engine orders lots by `mfg_date ASC, id ASC`, ensuring older batches are exhausted first to minimize expiration write-offs.

---

## 3. BOM Variance & Standard Costing Engine

The core technical differentiator of BatchWise is its mathematical modeling of the production run.

### A. Material Quantity Variance (MQV)
To decouple floor efficiency from market price fluctuations, the engine calculates MQV per ingredient:
$$\text{Standard Quantity for Actual Output} = \frac{\text{BOM Recipe Quantity}}{\text{Base Batch Quantity}} \times \text{Actual Finished Units Produced}$$
$$\text{MQV} = (\text{Standard Quantity for Actual Output} - \text{Actual Quantity Consumed}) \times \text{Standard Unit Cost}$$
* A negative value represents an **unfavorable variance** (e.g., dough scrap or spilled flour).
* A positive value represents a **favorable variance** (high yield efficiency).

### B. True Actual Production Unit Cost
Unlike simplistic systems that copy standard estimates, BatchWise computes actual production cost dynamically:
$$\text{Actual Unit Cost} = \frac{\sum(\text{Actual Quantity Consumed}_i \times \text{Batch Unit Cost}_i) + \text{Direct Labor} + \text{Factory Overhead}}{\text{Actual Finished Units Produced}}$$
The finished goods batch is inwarded into inventory with this exact unit cost basis, ensuring downstream gross margin and inventory balance sheets reflect true shop-floor economics.

### C. Yield Variance Percentage
$$\text{Yield Variance \%} = \left(\frac{\text{Actual Finished Units} - \text{Planned Target Units}}{\text{Planned Target Units}}\right) \times 100\%$$

---

## 4. Multi-Pack Architecture (Technical Differentiator)

In technical interviews and real-world bakeries, introducing a new SKU (e.g., *Family Bread 800g*) should not require duplicating the core dough recipe. 

BatchWise implements a **phantom/shared recipe pattern**:
1. The core formulation (Flour, Sugar, Yeast, Salt) is authored once under the master BOM.
2. The dynamic extension function `add_pack_size_bom(multiplier, packing_item_id)` scales ingredient ratios linearly ($2.0\times$ for 800g) while dynamically substituting packaging materials (`PM-POUCH-800` instead of `PM-POUCH-400`).
3. If the flour formulation changes, downstream packaging variants inherit updates without manual data duplication.

---

## 5. Security & Role-Based Access Control (RBAC) Matrix

| Business Role | Sales Orders | Order Approval | GST Invoicing | PO Creation | GRN Receipt | Production Runs | Customer Payments | Audit Reports |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Admin** | Create | **Approve** | **Generate** | Create | Receive | Execute | Record | Full Access |
| **Salesman** | Create | *Blocked* | *Blocked* | *Blocked* | *Blocked* | *Blocked* | *Blocked* | *Blocked* |
| **Purchase Mgr** | *Blocked* | *Blocked* | *Blocked* | **Create** | **Receive** | *Blocked* | *Blocked* | View |
| **Production Mgr**| *Blocked* | *Blocked* | *Blocked* | *Blocked* | *Blocked* | **Execute** | *Blocked* | View |
| **Auditor / Accounts**| View | *Blocked* | *Blocked* | View | View | View | **Record** | **Export** |

* Permissions are strictly enforced both at the service layer and within REST endpoints.
* A salesman attempting to approve an order or issue an invoice receives a hard `401/403 UnauthorizedError`.

---

## 6. Concurrency, ACID Guarantees & Shortage Intelligence

1. **ACID Transaction Boundaries**: All multi-table mutations run within atomic transactions using Python's `@contextmanager get_db()`. If any step fails, the entire transaction rolls back cleanly.
2. **Shortage Detection**: Before an order is committed, `check_stock_shortage()` evaluates active inventory. If demand exceeds stock, it traverses the active BOM, computes exact component replenishment requirements (including scrap allowances), and provides an instant procurement plan.
3. **Statutory GST Engine**: Automatically resolves intrastate (CGST 2.5% + SGST 2.5%) vs. interstate (IGST 5.0%) tax regimes based on State Code compliance (Karnataka Code 29). Produces PDF 1.4 compliant tax documents natively without external CLI dependencies.
