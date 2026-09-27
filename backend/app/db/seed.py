"""Seeds the DB with 5 scenarios that exercise every branch of the agent:

  milk-001  -> recommendation is correct                -> ACCEPT
  rice-001  -> recommendation over-buys                  -> MODIFY (down)
  eggs-002  -> nothing feasible / below supplier minimum -> REJECT + escalate
  oil-001   -> demand forecast missing                   -> INVESTIGATE
  milk-003  -> feasible qty blocked by storage on first
               try, agent replans automatically           -> MODIFY (self-correcting loop)

Run with: python -m app.db.seed
"""
from app.db.database import Base, engine, SessionLocal
from app.db import models as m


def seed():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # ---- Products -----------------------------------------------------
    milk = m.Product(sku="MILK-1L", name="Milk 1L", unit_cost=2.0)
    rice = m.Product(sku="RICE-5KG", name="Rice 5kg", unit_cost=10.0)
    eggs = m.Product(sku="EGGS-12", name="Eggs (dozen)", unit_cost=3.0)
    oil = m.Product(sku="OIL-1L", name="Cooking Oil 1L", unit_cost=5.0)
    db.add_all([milk, rice, eggs, oil])
    db.flush()

    # ---- Suppliers ------------------------------------------------------
    dairy_co = m.Supplier(name="Dairy Co", lead_time_days=3, min_order_qty=50, reliability_score=0.95)
    grain_co = m.Supplier(name="Grain Traders Ltd", lead_time_days=5, min_order_qty=20, reliability_score=0.9)
    farm_fresh = m.Supplier(name="Farm Fresh Eggs", lead_time_days=2, min_order_qty=100, reliability_score=0.8)
    oil_supplier = m.Supplier(name="Golden Oil Mills", lead_time_days=4, min_order_qty=30, reliability_score=0.9)
    db.add_all([dairy_co, grain_co, farm_fresh, oil_supplier])
    db.flush()

    db.add_all([
        m.ProductSupplier(product_id=milk.id, supplier_id=dairy_co.id, available_qty=1000, is_primary=True),
        m.ProductSupplier(product_id=rice.id, supplier_id=grain_co.id, available_qty=1000, is_primary=True),
        m.ProductSupplier(product_id=eggs.id, supplier_id=farm_fresh.id, available_qty=600, is_primary=True),
        m.ProductSupplier(product_id=oil.id, supplier_id=oil_supplier.id, available_qty=500, is_primary=True),
    ])

    # ---- Nodes (fulfillment centers) ------------------------------------
    node_milk_001 = m.Node(name="Store-001 (Milk)", storage_capacity_units=2000, storage_used_units=500, available_budget=5000)
    node_rice_001 = m.Node(name="Store-Rice", storage_capacity_units=500, storage_used_units=300, available_budget=3000)
    node_eggs_002 = m.Node(name="Store-Eggs", storage_capacity_units=1000, storage_used_units=950, available_budget=30)
    node_oil_001 = m.Node(name="Store-Oil", storage_capacity_units=800, storage_used_units=100, available_budget=2000)
    # NOTE: Milk/003 gets its OWN node (previously a bug shared it with Store-Eggs'
    # budget, which made the failure look like a budget problem instead of the
    # intended pure-storage constraint).
    node_milk_003 = m.Node(name="Store-002 (Milk replan)", storage_capacity_units=700, storage_used_units=550, available_budget=5000)

    db.add_all([node_milk_001, node_rice_001, node_eggs_002, node_oil_001, node_milk_003])
    db.flush()

    # ---- Inventory --------------------------------------------------------
    db.add_all([
        m.Inventory(product_id=milk.id, node_id=node_milk_001.id, quantity_on_hand=100),
        m.Inventory(product_id=rice.id, node_id=node_rice_001.id, quantity_on_hand=50),
        m.Inventory(product_id=eggs.id, node_id=node_eggs_002.id, quantity_on_hand=20),
        m.Inventory(product_id=oil.id, node_id=node_oil_001.id, quantity_on_hand=30),
        m.Inventory(product_id=milk.id, node_id=node_milk_003.id, quantity_on_hand=50),
    ])

    # ---- Demand -------------------------------------------------------------
    db.add_all([
        m.Demand(product_id=milk.id, node_id=node_milk_001.id, period="next_14_days", forecast_qty=900, actual_recent_qty=430),
        m.Demand(product_id=rice.id, node_id=node_rice_001.id, period="next_14_days", forecast_qty=700, actual_recent_qty=310),
        m.Demand(product_id=eggs.id, node_id=node_eggs_002.id, period="next_14_days", forecast_qty=400, actual_recent_qty=190),
        # Oil: forecast_qty is intentionally NULL -> agent must INVESTIGATE, not guess.
        m.Demand(product_id=oil.id, node_id=node_oil_001.id, period="next_14_days", forecast_qty=None, actual_recent_qty=150),
        m.Demand(product_id=milk.id, node_id=node_milk_003.id, period="next_14_days", forecast_qty=600, actual_recent_qty=590),
    ])

    # ---- Scenario "recommendations" (what a naive system suggested) --------
    # These aren't persisted as a table; the API takes them as request input,
    # mirroring how a real recommendation engine would call this service.

    db.commit()
    db.close()
    print("Seed complete: 4 products, 4 suppliers, 5 nodes, 5 scenarios ready.")


if __name__ == "__main__":
    seed()
