"""SQLAlchemy models for the AI Purchasing Agent.

Kept intentionally simple (SQLite, no migrations) since the assignment
explicitly allows mock data/DBs. Every table maps to something a real
buyer would look at: inventory, demand, suppliers, budgets, storage,
purchase orders.
"""
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
)
from sqlalchemy.orm import relationship

from app.db.database import Base


class Node(Base):
    """A fulfillment node (store / dark-store / warehouse)."""
    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    storage_capacity_units = Column(Float, nullable=False)
    storage_used_units = Column(Float, nullable=False, default=0)
    available_budget = Column(Float, nullable=False, default=0)

    @property
    def available_storage(self) -> float:
        return max(0.0, self.storage_capacity_units - self.storage_used_units)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    sku = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    unit_cost = Column(Float, nullable=False)


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    lead_time_days = Column(Integer, nullable=False)
    min_order_qty = Column(Integer, nullable=False, default=0)
    reliability_score = Column(Float, nullable=False, default=1.0)


class ProductSupplier(Base):
    """Which suppliers can fulfil a product, and how much they currently
    have available (used to simulate 'supplier can only fulfil part of
    the order')."""
    __tablename__ = "product_suppliers"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    available_qty = Column(Float, nullable=False)  # what the supplier can ship right now
    is_primary = Column(Boolean, default=True)

    product = relationship("Product")
    supplier = relationship("Supplier")


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    quantity_on_hand = Column(Float, nullable=False, default=0)

    product = relationship("Product")
    node = relationship("Node")


class Demand(Base):
    """Demand forecast + actual sales for anomaly detection (Scenario 3).
    forecast_qty may be NULL to simulate missing data (Scenario: investigate).
    """
    __tablename__ = "demand"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    period = Column(String, nullable=False)  # e.g. "next_14_days"
    forecast_qty = Column(Float, nullable=True)
    actual_recent_qty = Column(Float, nullable=True)  # recent actual sales, for anomaly check

    product = relationship("Product")
    node = relationship("Node")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    quantity = Column(Float, nullable=False)
    status = Column(String, nullable=False, default="draft")
    # draft -> validating -> pending_approval -> approved -> executed -> rejected
    reason = Column(Text, nullable=True)
    scenario_tag = Column(String, nullable=True)  # e.g. "milk-001" for test traceability
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product")
    node = relationship("Node")
    supplier = relationship("Supplier")


class AgentRun(Base):
    """Audit log of every agent decision + the full validation/replan trail.
    This is what backs the feedback-loop / evaluation story."""
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True)
    scenario_tag = Column(String, nullable=False)
    input_recommendation_qty = Column(Float, nullable=True)
    decision = Column(String, nullable=False)  # ACCEPT / MODIFY / REJECT / INVESTIGATE
    final_qty = Column(Float, nullable=True)
    explanation = Column(Text, nullable=False)
    trail_json = Column(Text, nullable=False)  # full tool calls + validation attempts, JSON
    requires_human_approval = Column(Boolean, default=False)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
