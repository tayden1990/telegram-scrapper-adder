import time
from collections import deque, defaultdict

class RateLimiter:
    def __init__(self, max_events: int, per_seconds: int):
        self.max = max_events
        self.per = per_seconds
        self.events = deque()

    def allow(self) -> bool:
        now = time.time()
        while self.events and now - self.events[0] > self.per:
            self.events.popleft()
        if len(self.events) < self.max:
            self.events.append(now)
            return True
        return False

class Quotas:
    def __init__(self, max_per_window: int, window_seconds: int):
        self.max = max_per_window
        self.per = window_seconds
        self.map = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        q = self.map[key]
        while q and now - q[0] > self.per:
            q.popleft()
        if len(q) < self.max:
            q.append(now)
            return True
        return False
