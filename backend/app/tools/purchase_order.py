"""Action tools: create_purchase_order + validate_purchase_order.

validate_purchase_order is the independent safety-check engine. It is
deliberately NOT part of the decision logic that picks a quantity -- it
re-derives hard limits from the DB itself and will reject/flag a PO the
decision engine proposed, which is exactly the feedback loop the
assignment asks for ("does the system validate the result of its own
decision, and what happens when it's wrong").
"""
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session
from app.db import models as m
from app.tools.lookups import check_budget, check_storage, check_supplier


@dataclass
class ValidationResult:
    ok: bool
    violations: list


def validate_purchase_order(db: Session, product_id: int, node_id: int, quantity: float) -> ValidationResult:
    violations = []

    product = db.query(m.Product).get(product_id)
    budget = check_budget(db, node_id)
    storage = check_storage(db, node_id)
    supplier = check_supplier(db, product_id)

    if quantity <= 0:
        violations.append("quantity_not_positive")
        return ValidationResult(ok=False, violations=violations)

    cost = quantity * product.unit_cost
    if not budget["found"] or cost > budget["available_budget"]:
        violations.append(
            f"budget_exceeded: cost={cost:.2f} > available={budget.get('available_budget')}"
        )

    if not storage["found"] or quantity > storage["available_storage"]:
        violations.append(
            f"storage_exceeded: qty={quantity} > available_storage={storage.get('available_storage')}"
        )

    if not supplier["found"]:
        violations.append("no_supplier_on_file")
    else:
        if quantity > supplier["available_qty"]:
            violations.append(
                f"exceeds_supplier_available: qty={quantity} > available={supplier['available_qty']}"
            )
        if quantity < supplier["min_order_qty"]:
            violations.append(
                f"below_supplier_minimum: qty={quantity} < min={supplier['min_order_qty']}"
            )

    return ValidationResult(ok=len(violations) == 0, violations=violations)


def create_purchase_order(
    db: Session,
    product_id: int,
    node_id: int,
    quantity: float,
    status: str = "draft",
    reason: Optional[str] = None,
    scenario_tag: Optional[str] = None,
    supplier_id: Optional[int] = None,
) -> m.PurchaseOrder:
    po = m.PurchaseOrder(
        product_id=product_id,
        node_id=node_id,
        supplier_id=supplier_id,
        quantity=quantity,
        status=status,
        reason=reason,
        scenario_tag=scenario_tag,
    )
    db.add(po)
    db.commit()
    db.refresh(po)
    return po
