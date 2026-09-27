# Architecture

## System overview

```mermaid
flowchart TD
    UI["Frontend (index.html)\nscenario buttons, live trail, approvals"]
    API["FastAPI app\n/agent/decide, /purchase-orders/*"]
    ENGINE["Agent engine\n(deterministic decision logic)"]
    TOOLS["Read-only tools\ninventory · demand · open POs\nsupplier · budget · storage"]
    VALIDATE["Validation engine\n(independent safety check)"]
    LLM["Optional LLM explainer\n(Claude, only rewrites text)"]
    DB[("SQLite\nproducts / nodes / inventory\ndemand / suppliers / POs / audit log")]

    UI -->|POST /agent/decide| API
    API --> ENGINE
    ENGINE -->|1. investigate| TOOLS
    TOOLS --> DB
    ENGINE -->|2. compute + decide| ENGINE
    ENGINE -->|3. create draft PO| DB
    ENGINE -->|4. validate| VALIDATE
    VALIDATE --> DB
    VALIDATE -->|fail| ENGINE
    ENGINE -->|replan, retry validate| VALIDATE
    ENGINE -->|final trail + explanation| API
    API -.->|use_llm_explanation=true| LLM
    LLM -.-> API
    API -->|decision, qty, trail| UI
    UI -->|approve / reject| API
    API -->|update PO status| DB
```

## The feedback loop (the core of the assignment)

```mermaid
sequenceDiagram
    participant E as Agent Engine
    participant V as Validation Engine
    participant DB as Database

    E->>DB: investigate (inventory, demand, budget, storage, supplier)
    E->>E: compute net_need, max_feasible, decision = MODIFY(550)
    E->>V: validate_purchase_order(qty=550)
    V->>DB: re-check budget / storage / supplier independently
    V-->>E: FAIL - storage_exceeded (available=150)
    E->>E: replan: qty = min(550, storage_available) = 150
    E->>V: validate_purchase_order(qty=150)
    V->>DB: re-check again
    V-->>E: OK
    E->>DB: create PurchaseOrder(qty=150, status=executed)
    E-->>Caller: decision=MODIFY, final_qty=150, trail=[2 validate attempts]
```

Two properties make this a real feedback loop rather than theater:

1. **The validator is independent of the decision logic.** It re-derives
   every hard limit from the database itself; it does not trust or inspect
   *how* the engine picked a number. It would reject a hand-crafted bad PO
   just as readily (see `test_validation_independently_catches_a_bad_po`).
2. **The replan step reads the validator's specific violation**, not just
   "it failed" — a `storage_exceeded` violation shrinks toward available
   storage, `budget_exceeded` shrinks toward what the budget allows, etc.
   If it still can't find a valid quantity above the supplier's minimum
   after a few attempts, it stops trying and escalates to a human instead
   of looping forever or returning a wrong number.

## Where human approval sits

```mermaid
flowchart LR
    D{Decision} -->|ACCEPT| A[Auto-execute]
    D -->|REJECT| H[Always → human]
    D -->|MODIFY| C{Order value > $1,000?}
    C -->|No| A
    C -->|Yes| H
    H --> P[pending_approval]
    P -->|POST approve| X[executed]
    P -->|POST reject| R[rejected]
```

This keeps low-risk, self-corrected purchases moving without a person in
the loop, while anything expensive or fundamentally blocked still gets a
human's sign-off — matching the assignment's ask for "when human approval
may be appropriate."

## Why deterministic core + optional LLM

The assignment states the purchasing recommendation should not be assumed
correct, and that an LLM should not own arithmetic or hard constraints. So
the engine (`app/agent/engine.py`) is plain, typed Python: every quantity,
every constraint check, and the decision type are computed the same way
every time, with or without an API key. `app/agent/llm.py` is a thin,
optional layer that can rewrite the explanation text for a human buyer using
Claude — it is given the trail as read-only context and is explicitly
instructed not to change the numbers or the decision. Any failure in that
layer (no key, network error, bad output) silently falls back to the
deterministic explanation, so the agent's actual behavior never depends on
an LLM being available.
