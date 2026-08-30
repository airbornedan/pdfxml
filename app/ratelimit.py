########################################################################
### RATE LIMIT -- per-IP sliding window, dependency-free. Guards the
### expensive PDF routes; no-op when TRUSTED_NETWORK is set. Per-process,
### in-memory (resets on restart).
########################################################################
import time
from collections import defaultdict, deque
from functools import wraps

from flask import abort, request

from app.extensions import TRUSTED_NETWORK, _cfg

### rule -> (max_hits, window_seconds)
_RULES = {
    "upload": (_cfg("ratelimit", "upload_per_minute", 10), 60),
    "render": (_cfg("ratelimit", "render_per_minute", 60), 60),
}

### rule -> { ip -> deque[monotonic timestamps] }
_hits = {rule: defaultdict(deque) for rule in _RULES}

### bound the per-IP dict -- drop drained deques past this many IPs
_MAX_TRACKED_IPS = 20_000


def _sweep(bucket, now, window):
    for ip in list(bucket):
        dq = bucket[ip]
        while dq and dq[0] <= now - window:
            dq.popleft()
        if not dq:
            del bucket[ip]


def limit(rule):
    max_hits, window = _RULES[rule]

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not TRUSTED_NETWORK:
                now = time.monotonic()
                bucket = _hits[rule]
                if len(bucket) > _MAX_TRACKED_IPS:
                    _sweep(bucket, now, window)
                dq = bucket[request.remote_addr or "-"]
                while dq and dq[0] <= now - window:
                    dq.popleft()
                if len(dq) >= max_hits:
                    abort(429)
                dq.append(now)
            return view(*args, **kwargs)

        return wrapped

    return decorator
