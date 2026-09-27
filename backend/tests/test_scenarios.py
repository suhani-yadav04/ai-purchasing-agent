"""Formal, repeatable version of the 5 scenario evaluations.

Each test checks the things the assignment asks us to evaluate:
  - Was the decision correct (right type: ACCEPT/MODIFY/REJECT/INVESTIGATE)?
  - Did it respect hard constraints (budget/storage/supplier)?
  - Did it produce a validated, consistent final quantity?
  - For the replan case: did the feedback loop actually engage and recover?

Run with:  cd backend && pytest -v
"""
import os
import sys
import pytest
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import Base, SessionLocal, engine
from app.db import models as m
from app.db.seed import seed
from app.agent.engine import run_agent
from app.tools.purchase_order import validate_purchase_order


@pytest.fixture(scope="module", autouse=True)
def fresh_db():
    seed()
    yield


@pytest.fixture()
def db():
    session = SessionLocal()
    yield session
    session.close()


def get_ids(db, product_sku, node_name):
    product = db.query(m.Product).filter_by(sku=product_sku).first()
    node = db.query(m.Node).filter_by(name=node_name).first()
    return product.id, node.id


def test_milk_001_accept(db):
    """Scenario 1: a correct recommendation should be accepted as-is."""
    pid, nid = get_ids(db, "MILK-1L", "Store-001 (Milk)")
    result = run_agent(db, pid, nid, recommended_qty=800, scenario_tag="milk-001")
    assert result.decision == "ACCEPT"
    assert result.final_qty == 800
    v = validate_purchase_order(db, pid, nid, result.final_qty)
    assert v.ok, v.violations
    assert result.requires_human_approval is False


def test_rice_001_modify_down(db):
    """Scenario 1/4: an over-sized recommendation gets corrected down to what's feasible."""
    pid, nid = get_ids(db, "RICE-5KG", "Store-Rice")
    result = run_agent(db, pid, nid, recommended_qty=800, scenario_tag="rice-001")
    assert result.decision == "MODIFY"
    assert result.final_qty == 200  # capped by available storage (200 units)
    v = validate_purchase_order(db, pid, nid, result.final_qty)
    assert v.ok, v.violations
    assert result.final_qty < 800


def test_eggs_002_reject_and_escalate(db):
    """Scenario 4: nothing feasible clears the supplier minimum -> reject + escalate."""
    pid, nid = get_ids(db, "EGGS-12", "Store-Eggs")
    result = run_agent(db, pid, nid, recommended_qty=500, scenario_tag="eggs-002")
    assert result.decision == "REJECT"
    assert result.requires_human_approval is True
    po = db.query(m.PurchaseOrder).get(result.purchase_order_id)
    assert po.status in ("rejected", "pending_approval")


def test_oil_001_investigate_missing_data(db):
    """Scenario 3: missing demand forecast -> agent must not guess."""
    pid, nid = get_ids(db, "OIL-1L", "Store-Oil")
    result = run_agent(db, pid, nid, recommended_qty=300, scenario_tag="oil-001")
    assert result.decision == "INVESTIGATE"
    assert result.final_qty is None
    assert "demand_forecast" in result.explanation or "missing" in result.explanation.lower()


def test_milk_003_replan_feedback_loop(db):
    """Scenario 4 (the centerpiece): first proposal violates storage, the agent
    automatically replans to a smaller quantity, re-validates, and only then
    (being within the auto-approve threshold) executes without a human."""
    pid, nid = get_ids(db, "MILK-1L", "Store-002 (Milk replan)")
    result = run_agent(db, pid, nid, recommended_qty=600, scenario_tag="milk-003")

    attempts = [s for s in result.trail if s["step"] == "validate_attempt"]
    assert len(attempts) >= 2, "expected at least one failed attempt before a successful replan"
    assert attempts[0]["ok"] is False
    assert attempts[-1]["ok"] is True

    assert result.decision == "MODIFY"
    assert result.final_qty == 150  # exactly the available storage headroom
    v = validate_purchase_order(db, pid, nid, result.final_qty)
    assert v.ok, v.violations
    # Small, in-policy correction -> should auto-execute, not need a human.
    assert result.requires_human_approval is False


def test_validation_independently_catches_a_bad_po():
    """Sanity check on the validation engine itself, independent of the agent:
    it must reject a PO that violates a hard constraint even if nothing
    upstream flagged it."""
    session = SessionLocal()
    pid, nid = get_ids(session, "EGGS-12", "Store-Eggs")
    result = validate_purchase_order(session, pid, nid, quantity=1000)  # way over storage/budget
    assert result.ok is False
    assert any("budget_exceeded" in v or "storage_exceeded" in v for v in result.violations)
    session.close()
