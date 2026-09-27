# AI Purchasing Agent

A full-stack agent that reviews a purchasing recommendation, investigates the
real constraints behind it (inventory, demand, open POs, supplier, budget,
storage), decides **ACCEPT / MODIFY / REJECT / INVESTIGATE**, validates its
own proposed purchase order against those same constraints, and
**automatically replans if validation fails** — escalating to a human only
when it genuinely can't resolve things on its own.

Built for the Rappi AI Purchasing Agent assignment. Implements **Scenario 1**
(recommendation review) and **Scenario 4** (purchasing constraints) end to
end, including the self-correcting feedback loop, plus the missing-data
"investigate" path (touches Scenario 3) and a supplier-shortfall style
rejection + escalation path (touches Scenario 2).

---

## 1. Quick start

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.db.seed          # creates buyer_agent.db with 5 ready-made scenarios
uvicorn app.api.main:app --reload --port 8000
```

Then open `frontend/index.html` directly in a browser (or serve it: `python3
-m http.server 5500` from the `frontend/` folder). It talks to
`http://localhost:8000` by default — editable in the top-right of the page.

Run the automated evaluation suite:

```bash
cd backend
pytest -v
```

No API key is required for any of the above — see [Section 4](#4-role-of-the-llm)
for what an `ANTHROPIC_API_KEY` does and does not change.

---

## 2. What the agent actually does

For a given `(product, node, recommended_qty)`:

1. **Investigate** — calls 6 read-only tools: `check_inventory`,
   `check_demand`, `check_open_purchase_orders`, `check_supplier`,
   `check_budget`, `check_storage`.
2. **Missing-data guard** — if demand forecast, supplier info, budget, or
   storage data isn't available, the agent stops and returns
   `INVESTIGATE` rather than guessing. (This is the Oil/001-style scenario:
   a forecast simply isn't on file.)
3. **Compute** — derives `net_need = demand − inventory − open_POs`, and a
   hard `max_feasible` quantity as the minimum of what budget, storage, and
   the supplier can actually support.
4. **Decide**:
   - `max_feasible` below the supplier's minimum order → **REJECT**, escalate.
   - recommendation is feasible and close to net need → **ACCEPT**.
   - otherwise → **MODIFY** toward `min(recommended, net_need)`.
5. **Create + validate** — a draft purchase order is created and run through
   an **independent validation engine** (`validate_purchase_order`) that
   re-derives budget/storage/supplier limits from the database itself. This
   engine has no knowledge of how the quantity was chosen — it will happily
   reject a number the decision step got wrong.
6. **Replan on failure** — if validation fails, the agent shrinks the
   quantity to the tightest violated constraint and re-validates (up to 3
   attempts) before giving up and escalating. **This is the core
   interview-differentiator**: a purchasing decision that survives contact
   with its own safety check.
7. **Human-approval gate** — `ACCEPT` never needs a human. `REJECT` always
   does. `MODIFY` auto-executes only if the resulting order's dollar value is
   below a policy threshold ($1,000) — small, in-policy corrections don't
   need a person; larger ones do.

Every step is logged to an `AgentRun` audit row (`trail_json`) — this is what
the frontend's "full tool-call + validation trail" panel renders, and it's
the artifact an evaluator would use to check *why* the agent did what it did.

## 3. Why the logic is deterministic, not LLM-driven

The assignment explicitly frames the recommendation as untrustworthy and
says an LLM shouldn't own arithmetic or hard constraints. So all quantity
math, constraint checks, and the decision type are plain Python — testable,
debuggable, and reproducible without any API key. This also makes the
evaluation suite meaningful: the same 5 scenarios produce the same decisions
every run.

## 4. Role of the LLM

`ANTHROPIC_API_KEY` is entirely optional (`backend/.env.example`). If set,
and the caller passes `"use_llm_explanation": true` to `/agent/decide`, the
deterministic explanation + full trail are handed to Claude purely to be
**rephrased** for a human buyer — the prompt explicitly forbids inventing
numbers or changing the decision. If the key is missing, invalid, or the API
call fails for any reason, the deterministic explanation is used verbatim.
The agent's correctness never depends on this layer.

## 5. Data model

SQLite via SQLAlchemy (`backend/app/db/models.py`): `Product`, `Supplier`,
`ProductSupplier` (what a supplier can currently ship), `Node` (a
store/fulfillment center, with storage capacity and budget), `Inventory`,
`Demand` (forecast + recent actuals, forecast can be `NULL` to simulate
missing data), `PurchaseOrder`, and `AgentRun` (audit log).

`backend/app/db/seed.py` seeds 5 scenarios (see Section 6) with realistic,
hand-tuned numbers so each one deterministically exercises a different
branch of the agent.

## 6. Seeded scenarios

| Tag | Product / Node | Recommended | What happens | Decision |
|---|---|---|---|---|
| `milk-001` | Milk / Store-001 | 800 | Matches net need, within all limits | **ACCEPT** |
| `rice-001` | Rice / Store-Rice | 800 | Over-buys; storage only allows 200 | **MODIFY → 200** |
| `eggs-002` | Eggs / Store-Eggs | 500 | Budget is nearly exhausted; max feasible (10) is below the supplier's 100-unit minimum | **REJECT**, escalate |
| `oil-001` | Oil / Store-Oil | 300 | Demand forecast is missing from the system | **INVESTIGATE** |
| `milk-003` | Milk / Store-002 | 600 | First proposal (550) fails storage validation, agent automatically replans down to the 150-unit headroom, re-validates, passes, auto-executes (small $) | **MODIFY → 150** (feedback loop) |

## 7. API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness check |
| GET | `/catalog` | products, nodes, and the 5 demo scenarios (for the frontend) |
| POST | `/agent/decide` | run the agent: `{product_id, node_id, recommended_qty, scenario_tag?, use_llm_explanation?}` |
| GET | `/agent/runs` | audit log of every decision made |
| GET | `/purchase-orders?status=` | list purchase orders, optionally filtered |
| POST | `/purchase-orders/{id}/approve` | human approves a `pending_approval` PO |
| POST | `/purchase-orders/{id}/reject` | human rejects a `pending_approval` PO |

Interactive docs at `http://localhost:8000/docs` once the server is running.

## 8. Evaluation approach

See `backend/tests/test_scenarios.py` — a pytest suite that runs all 5
scenarios and checks, per the assignment's own evaluation criteria:
- **Was the decision correct?** (right decision type per scenario)
- **Did it respect constraints?** (asserts the final quantity independently
  re-validates clean against budget/storage/supplier)
- **Did it obtain necessary information first?** (Oil/001 must not silently
  invent a number when demand data is missing)
- **What happens when the initial action doesn't work?** (Milk/003 asserts
  the trail contains a failed validation attempt *followed by* a successful
  one — i.e. the replan loop actually engaged, not just that the final
  answer happens to be right)
- A standalone test also hits `validate_purchase_order` directly with a
  deliberately bad quantity, to prove the safety check works independently
  of the agent that's supposed to respect it.

Uses its own SQLite file (`test_buyer_agent.db`) so running tests never
disturbs the demo data the frontend/API server is using.

## 9. What's not built (scope)

Per the assignment, breadth was intentionally deprioritized versus depth on
the core loop. Not implemented: a real LLM-driven planning step (tools are
called in a fixed deterministic order rather than an LLM choosing which
tool to call next — this was a deliberate choice, see Section 3), a second
supplier fallback / re-sourcing flow for Scenario 2 (the reject+escalate
path stands in for it), and auth/multi-user approval workflows.

## 10. Repo layout

```
backend/
  app/
    db/        # models, engine, seed data
    tools/     # read-only lookups + create/validate purchase order
    agent/     # deterministic decision engine + optional LLM explainer
    api/       # FastAPI app
  tests/       # pytest evaluation suite
  requirements.txt
  .env.example
frontend/
  index.html   # single-file demo console (scenario buttons, live trail, approvals)
ARCHITECTURE.md
```

See `ARCHITECTURE.md` for a system diagram and a written walkthrough of the
feedback loop.
