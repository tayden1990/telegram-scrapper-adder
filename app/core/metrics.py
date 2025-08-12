from prometheus_client import Counter

jobs_total = Counter(
    "jobs_total",
    "Jobs processed by status",
    labelnames=("status",),
)
