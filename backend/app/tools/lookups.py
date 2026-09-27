"""Read-only 'tools' the agent calls to investigate a situation.

Each function is a plain, typed Python function (no framework needed to
call it) so it can be used directly today and wrapped as an LLM tool
schema later with zero logic changes. Every tool returns a plain dict
with an explicit `found` flag so the agent can distinguish
"zero" from "we don't have this data" (this is what drives Scenario:
INVESTIGATE for Oil/001).
"""
from sqlalchemy.orm import Session
from app.db import models as m


def check_inventory(db: Session, product_id: int, node_id: int) -> dict:
    row = (
        db.query(m.Inventory)
        .filter_by(product_id=product_id, node_id=node_id)
        .first()
    )
    if not row:
        return {"found": False, "quantity_on_hand": None}
    return {"found": True, "quantity_on_hand": row.quantity_on_hand}


def check_demand(db: Session, product_id: int, node_id: int) -> dict:
    row = (
        db.query(m.Demand)
        .filter_by(product_id=product_id, node_id=node_id)
        .first()
    )
    if not row:
        return {"found": False, "forecast_qty": None, "actual_recent_qty": None, "anomaly": False}

    anomaly = False
    if row.forecast_qty and row.actual_recent_qty:
        # crude anomaly signal: recent actuals imply >50% more demand than forecast assumed
        implied_full_period = row.actual_recent_qty * 2  # actual_recent_qty covers ~half the period
        if implied_full_period > row.forecast_qty * 1.5:
            anomaly = True

    return {
        "found": True,
        "forecast_qty": row.forecast_qty,  # may legitimately be None -> missing data
        "actual_recent_qty": row.actual_recent_qty,
        "anomaly": anomaly,
    }


def check_open_purchase_orders(db: Session, product_id: int, node_id: int) -> dict:
    rows = (
        db.query(m.PurchaseOrder)
        .filter(
            m.PurchaseOrder.product_id == product_id,
            m.PurchaseOrder.node_id == node_id,
            m.PurchaseOrder.status.in_(["pending_approval", "approved", "executed"]),
        )
        .all()
    )
    total_qty = sum(r.quantity for r in rows)
    return {"found": True, "open_po_qty": total_qty, "count": len(rows)}


def check_supplier(db: Session, product_id: int) -> dict:
    ps = (
        db.query(m.ProductSupplier)
        .filter_by(product_id=product_id, is_primary=True)
        .first()
    )
    if not ps:
        return {"found": False}
    supplier = db.query(m.Supplier).get(ps.supplier_id)
    return {
        "found": True,
        "supplier_id": supplier.id,
        "supplier_name": supplier.name,
        "available_qty": ps.available_qty,
        "min_order_qty": supplier.min_order_qty,
        "lead_time_days": supplier.lead_time_days,
        "reliability_score": supplier.reliability_score,
    }


def check_budget(db: Session, node_id: int) -> dict:
    node = db.query(m.Node).get(node_id)
    if not node:
        return {"found": False, "available_budget": None}
    return {"found": True, "available_budget": node.available_budget}


def check_storage(db: Session, node_id: int) -> dict:
    node = db.query(m.Node).get(node_id)
    if not node:
        return {"found": False, "available_storage": None}
    return {
        "found": True,
        "capacity": node.storage_capacity_units,
        "used": node.storage_used_units,
        "available_storage": node.available_storage,
    }
