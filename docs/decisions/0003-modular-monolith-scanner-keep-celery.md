# 0003 — Scanner stays one process (modular monolith); Celery kept for alerts/maintenance

Date: 2026-10-23. Status: proposed (architect, Phase 5; confirm at U2).

**Context.** `scanner/service.py` is a 1048-line god object (B4/TD-05). Options range from
splitting it into classes to splitting the scanner into several services. Celery is used for a
low-volume, single-producer workload (B8), but isolates the Telegram token from the scanner.

**Decision.** Keep one scanner process and container. Split `Scanner` into in-process
collaborators (`SweepPipeline`, `ScannerRuntime`, `TaskSupervisor`, `TickerCollector`,
`HealthRecorder`, `FeeRefiner`, `BookProvider`, `CandidateEvaluator`, `QuarantineCoordinator`,
`EpisodeCoordinator`, `AlertGate`, `MetadataRefresher`) step by step (migration plan C1–C8).
Keep Celery + Redis broker for alerts, digest and maintenance. Enforce one scanner instance with
a Redis lease.

**Alternatives.** (a) Separate services for tickers, books, evaluation over Redis pub/sub —
rejected: adds latency and failure modes to a sub-second path for no scale need. (b) Replace
Celery with an in-process sender — rejected: the scanner would hold the Telegram token and lose
retry/at-least-once delivery. (c) Leave the god object — rejected: blocks review and Stage 2.

**Consequences.** No new infrastructure. Horizontal scale of the scanner is not a goal before GO.
Stage 2 executor, if any, is a separate container (target.md §7).
