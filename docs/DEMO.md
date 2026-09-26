# Demo Guide

## 5-minute reviewer path

### 1. Open Research Workspace

The main workspace should show the persisted research directions and current tracking summary.

Current local dataset used during development contains 203 research directions.

### 2. Open one direction

A direction detail page shows:

- hypothesis / description
- material statistics
- source families
- latest research
- history
- actor observations
- behavior windows
- repeated patterns

### 3. Verify the evidence-first boundary

The UI describes observed evidence and behavior.

It does not automatically output a market verdict.

### 4. Run one direction manually

Use the single-direction research action.

Expected behavior:

- creates or reuses one persisted run
- does not start all directions
- remains usable while global auto tracking is paused
- can reconnect after navigation / refresh

### 5. Review behavior intelligence

For directions with enough current observations, inspect:

- public actors
- workflows
- workarounds
- repeated patterns
- 7d / 30d deltas

These are descriptive signals only.

---

## Local startup

### Backend

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Docker is not required for the default Research Workspace.

### Frontend

```bash
cd dashboard
npm run dev
```

Open:

`http://localhost:5173/`

---

## Representative regressions

```bash
python run_signalforge_behavior_tracking_v1_regression.py
python run_signalforge_tracking_research_persistence_v2_5_3_smoke.py
python run_signalforge_dockerless_local_mode_regression.py
python run_signalforge_dockerless_readpath_fix_v1_regression.py
```

Expected themes:

- actor state persists
- patterns require independent actors
- rolling windows exist
- single-item run persists
- Dockerless mode starts without PostgreSQL
- list/detail GET stays read-only
- market truth remains untouched

---

## Demo boundary

This demo proves the research workflow and engineering boundaries.

It does **not** prove:

- a specific market is validated
- willingness to pay exists
- revenue exists
- SignalForge can predict successful products
