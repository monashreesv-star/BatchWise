from app.database import get_db
from app.security import has_permission
from app.engine.bom_production import create_work_order, execute_production_run

class ProductionServiceError(Exception):
    pass

class UnauthorizedError(ProductionServiceError):
    pass

def create_production_order(conn, user: dict, bom_id: int, target_qty: float,
                            batch_number: str, start_date: str = None, notes: str = None):
    if not has_permission(user["role"], "production:create"):
        raise UnauthorizedError(f"Role '{user['role']}' is not authorized to create production orders.")

    wo_id = create_work_order(
        conn, bom_id=bom_id, target_qty=target_qty, batch_number=batch_number,
        start_date=start_date, created_by=user["id"], notes=notes
    )
    return {"wo_id": wo_id, "status": "planned"}

def complete_production_run(conn, user: dict, wo_id: int, actual_qty_produced: float,
                            consumptions: list, labor_cost: float = 0.0,
                            overhead_cost: float = 0.0, completion_date: str = None):
    if not has_permission(user["role"], "production:execute"):
        raise UnauthorizedError(f"Role '{user['role']}' is not authorized to execute production runs.")

    result = execute_production_run(
        conn, wo_id=wo_id, actual_qty_produced=actual_qty_produced,
        consumptions=consumptions, labor_cost=labor_cost, overhead_cost=overhead_cost,
        completion_date=completion_date, created_by=user["id"]
    )
    return result
