# What was NOT verified

| Area | Why | Confidence |
|---|---|---|
| Docker image build and `up` | Live stack already running; avoided touching it | n/a |
| ccxt.pro WebSocket behaviour (quiet markets, resubscribe) | Needs live run | Low |
| Real DB row volumes / growth | Data wiped (R-01); estimates only | Low |
| Exchange ToS, Argentina regulation, taxes | No web sources consulted | Low |
| Dev dependency vulnerabilities | pip-audit run on runtime deps only | Medium |
| Celery payload versioning (events.py) | Not fully read | Low |
| 25 `except Exception` handlers | Not reviewed one by one | Low |
| Transfer-status parsers vs real keyed responses | No keys for agents | Low |
| Integration tests meaning | Ran once destructively; 12 passed | Medium |
| Production config | Only a local compose exists | n/a |
