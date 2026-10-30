# 0003 — Scanner stays one process (modular monolith); Celery kept for alerts/maintenance

Date: 2026-10-23. Status: accepted (architect, delegated by the user).
Revised 2026-10-23: split reduced from 12 new classes to 5, singleton lease simplified.

## Context
`scanner/service.py` is a 1048-line god object (B4/TD-05): ~40 methods, all state in one class.
Part of the logic already lives in sibling modules (`episodes.py`, `health.py`,
`quarantine.py`, `streams.py`, `universe.py`). Celery runs a low-volume, single-producer
workload (B8), but it keeps the Telegram token out of the scanner. One developer, MVP goal is a
GO/NO-GO verdict, not scale.

## Decision drivers
- Reviewability and unit-testability of the sweep.
- No new failure modes on the sub-second sweep path.
- Secret isolation (Telegram token) and at-least-once alert delivery.
- Smallest change that achieves the above (one person, behaviour-preserving steps).

## Considered options
1. Split by **cohesion and owned state** into a few in-process classes; keep Celery. **(chosen)**
2. Fine-grained split into ~12 classes (previous draft) — rejected: many 1-3 method classes,
   more wiring than logic, no testability gain over option 1.
3. Separate services (tickers, books, evaluation) over Redis pub/sub — rejected: latency and
   failure modes on the hot path, no scale need.
4. Replace Celery with an in-process sender — rejected: scanner would hold the Telegram token
   and lose retries.
5. Leave the god object — rejected: blocks review.

## Decision
- One scanner process and container. Extract only classes that own state or a clear stage:
  `ScannerRuntime` (run loop, stop, background-task supervision, heartbeat, lease),
  `TickerCollector` (ticker fan-out + batched health recording), `BookProvider` (REST/WS books,
  semaphores, `OrderBookStreams`), `FeeRefiner` (account-fee cache), `CandidateEvaluator`
  (per-route evaluation with deadline). Quarantine, episode/alert and metadata-refresh glue moves
  into the existing `quarantine.py`, `episodes.py` and `universe.py` modules.
- `Scanner` keeps its name and becomes the thin sweep pipeline (stage ordering only). No rename.
- Dependencies are constructor-injected, acyclic, wired only in `container.py`.
- Stop splitting when every scanner module is < ~300 lines and unit-testable alone.
- Keep Celery + Redis broker for alerts, digest, maintenance.
- One scanner instance: Redis `SET NX PX` lease renewed each sweep; a second instance waits.
  No fencing tokens or Redlock (single host, single Redis).

## Consequences
- Good: no new infrastructure; each step is a code move under characterization tests.
- Good: fewer classes to name, wire and review than the previous draft.
- Bad: classes are larger (up to ~300 lines) than a fine-grained split; acceptable for MVP.
- Bad: no horizontal scale of the scanner; not a goal before GO.

## Confirmation
Migration plan C0-C6 and C10; tech-lead checks module size, wiring only in `container.py`,
and the async contract.
