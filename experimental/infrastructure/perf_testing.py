"""
STC Framework — Performance Testing Framework
infrastructure/perf_testing.py

Performance testing, SLO validation, and capacity planning:
  - Load profile simulation (baseline, peak, stress, soak)
  - SLO/SLI measurement and error budget tracking
  - Latency histogram collection (p50/p95/p99)
  - Capacity model validation
  - Performance regression detection

Produces structured reports for EA review and SRE dashboards.
"""

import json
import math
import time
import random
import logging
import statistics
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("stc.infrastructure.perf_testing")


# ── SLO Definitions ─────────────────────────────────────────────────────────

@dataclass
class SLODefinition:
    name: str
    sli_description: str
    target: float
    unit: str
    measurement: str
    error_budget_period_days: int = 30

    @property
    def error_budget(self) -> float:
        """Error budget as fraction of period."""
        if "%" in self.unit:
            return 1.0 - self.target / 100
        return None


STC_SLOS = [
    SLODefinition("availability", "Successful requests / total requests", 99.95, "%",
                   "ALB 5xx rate + health check"),
    SLODefinition("latency_p50", "50th percentile request latency", 3.0, "seconds",
                   "OTel trace duration"),
    SLODefinition("latency_p95", "95th percentile request latency", 6.0, "seconds",
                   "OTel trace duration"),
    SLODefinition("latency_p99", "99th percentile request latency", 10.0, "seconds",
                   "OTel trace duration"),
    SLODefinition("error_rate", "HTTP 5xx / total requests", 1.0, "%",
                   "Request counter"),
    SLODefinition("hallucination_rate", "Critic-flagged hallucinations / total", 2.0, "%",
                   "Critic verdict logs"),
    SLODefinition("throughput", "Sustained requests per second", 100, "rps",
                   "Request counter"),
]


# ── Load Profiles ───────────────────────────────────────────────────────────

class LoadProfile(Enum):
    BASELINE = "baseline"       # 100 concurrent, 5 min steady
    PEAK = "peak"               # 500 concurrent, ramp + sustain
    STRESS = "stress"           # Ramp until failure
    SOAK = "soak"               # 200 concurrent, 4 hours


@dataclass
class LoadConfig:
    profile: LoadProfile
    concurrent_users: int
    duration_seconds: int
    ramp_seconds: int = 0
    requests_per_user: int = 0  # 0 = unlimited (rate-based)
    target_rps: int = 0         # Target requests/second


LOAD_CONFIGS = {
    LoadProfile.BASELINE: LoadConfig(
        LoadProfile.BASELINE, concurrent_users=100, duration_seconds=300,
        ramp_seconds=30, target_rps=50),
    LoadProfile.PEAK: LoadConfig(
        LoadProfile.PEAK, concurrent_users=500, duration_seconds=900,
        ramp_seconds=300, target_rps=200),
    LoadProfile.STRESS: LoadConfig(
        LoadProfile.STRESS, concurrent_users=1000, duration_seconds=600,
        ramp_seconds=600, target_rps=0),  # No target, push until break
    LoadProfile.SOAK: LoadConfig(
        LoadProfile.SOAK, concurrent_users=200, duration_seconds=14400,
        ramp_seconds=60, target_rps=80),
}


# ── Metrics Collection ──────────────────────────────────────────────────────

class MetricsCollector:
    """Thread-safe metrics collection during load tests."""

    def __init__(self):
        self._lock = threading.Lock()
        self._latencies: List[float] = []
        self._errors: List[str] = []
        self._successes: int = 0
        self._total: int = 0
        self._start_time: float = 0
        self._status_codes: Dict[int, int] = defaultdict(int)
        self._time_series: List[Dict[str, Any]] = []  # 1-second buckets
        self._current_bucket: int = 0
        self._bucket_data: Dict[int, Dict] = defaultdict(
            lambda: {"requests": 0, "errors": 0, "latencies": []})

    def start(self):
        self._start_time = time.time()

    def record(self, latency_seconds: float, status_code: int, error: str = ""):
        with self._lock:
            self._total += 1
            self._status_codes[status_code] += 1

            if 200 <= status_code < 400:
                self._successes += 1
                self._latencies.append(latency_seconds)
            else:
                self._errors.append(error or f"HTTP {status_code}")

            # Time series bucket
            bucket = int(time.time() - self._start_time)
            bd = self._bucket_data[bucket]
            bd["requests"] += 1
            if status_code >= 500:
                bd["errors"] += 1
            bd["latencies"].append(latency_seconds)

    def report(self) -> Dict[str, Any]:
        with self._lock:
            elapsed = time.time() - self._start_time if self._start_time else 0
            latencies = sorted(self._latencies)
            n = len(latencies)

            def percentile(pct):
                if not latencies:
                    return 0
                idx = int(n * pct / 100)
                return latencies[min(idx, n - 1)]

            rps = self._total / elapsed if elapsed > 0 else 0
            error_rate = len(self._errors) / self._total * 100 if self._total > 0 else 0
            availability = self._successes / self._total * 100 if self._total > 0 else 0

            return {
                "total_requests": self._total,
                "successes": self._successes,
                "errors": len(self._errors),
                "duration_seconds": round(elapsed, 2),
                "requests_per_second": round(rps, 2),
                "availability": round(availability, 4),
                "error_rate": round(error_rate, 4),
                "latency": {
                    "min": round(min(latencies), 4) if latencies else 0,
                    "max": round(max(latencies), 4) if latencies else 0,
                    "mean": round(statistics.mean(latencies), 4) if latencies else 0,
                    "median": round(statistics.median(latencies), 4) if latencies else 0,
                    "p50": round(percentile(50), 4),
                    "p95": round(percentile(95), 4),
                    "p99": round(percentile(99), 4),
                    "stddev": round(statistics.stdev(latencies), 4) if len(latencies) > 1 else 0,
                },
                "status_codes": dict(self._status_codes),
            }


# ── SLO Validator ───────────────────────────────────────────────────────────

class SLOValidator:
    """Validates performance test results against SLO targets."""

    def __init__(self, slos: Optional[List[SLODefinition]] = None):
        self.slos = slos or STC_SLOS

    def validate(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        results = []

        for slo in self.slos:
            actual = self._extract_metric(slo.name, metrics)
            if actual is None:
                results.append({
                    "slo": slo.name, "target": slo.target, "actual": None,
                    "unit": slo.unit, "passed": None, "status": "UNMEASURED",
                })
                continue

            if slo.name.startswith("latency"):
                passed = actual <= slo.target
            elif slo.name == "availability":
                passed = actual >= slo.target
            elif slo.name == "error_rate" or slo.name == "hallucination_rate":
                passed = actual <= slo.target
            elif slo.name == "throughput":
                passed = actual >= slo.target
            else:
                passed = actual <= slo.target

            margin = abs(actual - slo.target) / slo.target * 100 if slo.target != 0 else 0

            results.append({
                "slo": slo.name,
                "target": slo.target,
                "actual": round(actual, 4),
                "unit": slo.unit,
                "passed": passed,
                "margin": round(margin, 2),
                "status": "PASS" if passed else "FAIL",
            })

        all_passed = all(r["passed"] for r in results if r["passed"] is not None)
        measured = [r for r in results if r["passed"] is not None]

        return {
            "overall": "PASS" if all_passed else "FAIL",
            "slos_evaluated": len(measured),
            "slos_passed": sum(1 for r in measured if r["passed"]),
            "slos_failed": sum(1 for r in measured if not r["passed"]),
            "results": results,
        }

    def _extract_metric(self, slo_name: str, metrics: Dict) -> Optional[float]:
        if slo_name == "availability":
            return metrics.get("availability")
        elif slo_name == "latency_p50":
            return metrics.get("latency", {}).get("p50")
        elif slo_name == "latency_p95":
            return metrics.get("latency", {}).get("p95")
        elif slo_name == "latency_p99":
            return metrics.get("latency", {}).get("p99")
        elif slo_name == "error_rate":
            return metrics.get("error_rate")
        elif slo_name == "throughput":
            return metrics.get("requests_per_second")
        return None


# ── Performance Test Runner ─────────────────────────────────────────────────

class PerformanceTestRunner:
    """
    Runs simulated performance tests against the STC pipeline.

    In production, this would be replaced by k6/Locust scripts hitting
    the actual endpoints. This module provides the framework, metrics
    collection, SLO validation, and reporting.

    Usage:
        runner = PerformanceTestRunner()
        report = runner.run_load_test(LoadProfile.BASELINE, pipeline_func)
    """

    def __init__(self, audit_callback=None):
        self._audit_callback = audit_callback
        self._history: List[Dict[str, Any]] = []

    def run_load_test(self, profile: LoadProfile,
                      pipeline_func: Optional[Callable] = None,
                      config: Optional[LoadConfig] = None) -> Dict[str, Any]:
        """
        Run a load test with the given profile.

        Args:
            profile: Load profile (baseline, peak, stress, soak)
            pipeline_func: Function simulating the STC pipeline
                          Signature: () -> (status_code, latency_seconds)
            config: Override default config for this profile
        """
        cfg = config or LOAD_CONFIGS[profile]
        func = pipeline_func or self._default_simulator

        collector = MetricsCollector()
        collector.start()

        start_time = time.time()
        test_id = f"perf-{profile.value}-{int(start_time)}"

        logger.info(f"Starting {profile.value} test: {cfg.concurrent_users} users, "
                     f"{cfg.duration_seconds}s duration")

        # Simulated load generation
        # In production, replace with k6/Locust integration
        threads = []
        stop_event = threading.Event()

        def worker(worker_id: int):
            while not stop_event.is_set():
                elapsed = time.time() - start_time
                if elapsed >= cfg.duration_seconds:
                    break

                # Ramp: only use fraction of workers during ramp period
                if cfg.ramp_seconds > 0 and elapsed < cfg.ramp_seconds:
                    ramp_fraction = elapsed / cfg.ramp_seconds
                    if worker_id > cfg.concurrent_users * ramp_fraction:
                        time.sleep(0.1)
                        continue

                try:
                    req_start = time.time()
                    status, latency = func()
                    collector.record(latency, status)
                except Exception as e:
                    collector.record(0, 500, str(e))

                # Rate limiting per worker
                if cfg.target_rps > 0:
                    target_delay = cfg.concurrent_users / cfg.target_rps
                    actual_delay = time.time() - req_start
                    if actual_delay < target_delay:
                        time.sleep(target_delay - actual_delay)

        # Launch workers
        actual_workers = min(cfg.concurrent_users, 50)  # Cap for simulation
        for i in range(actual_workers):
            t = threading.Thread(target=worker, args=(i,), daemon=True)
            threads.append(t)
            t.start()

        # Wait for duration or early termination
        time.sleep(min(cfg.duration_seconds, 10))  # Cap at 10s for demo
        stop_event.set()

        for t in threads:
            t.join(timeout=5)

        # Collect results
        metrics = collector.report()

        # Validate SLOs
        slo_results = SLOValidator().validate(metrics)

        report = {
            "test_id": test_id,
            "profile": profile.value,
            "config": {
                "concurrent_users": cfg.concurrent_users,
                "duration_seconds": cfg.duration_seconds,
                "ramp_seconds": cfg.ramp_seconds,
                "target_rps": cfg.target_rps,
            },
            "metrics": metrics,
            "slo_validation": slo_results,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._history.append(report)

        if self._audit_callback:
            self._audit_callback({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "component": "infrastructure.perf_testing",
                "event_type": "load_test_completed",
                "details": {
                    "test_id": test_id,
                    "profile": profile.value,
                    "overall_slo": slo_results["overall"],
                    "requests": metrics["total_requests"],
                    "rps": metrics["requests_per_second"],
                    "p99": metrics["latency"]["p99"],
                    "error_rate": metrics["error_rate"],
                },
            })

        return report

    def regression_check(self, current: Dict, baseline: Dict,
                         threshold_pct: float = 20.0) -> Dict[str, Any]:
        """
        Compare current test results against a baseline for regression.
        Flags any metric that degraded by more than threshold_pct.
        """
        regressions = []

        for metric in ["p50", "p95", "p99"]:
            curr_val = current.get("metrics", {}).get("latency", {}).get(metric, 0)
            base_val = baseline.get("metrics", {}).get("latency", {}).get(metric, 0)
            if base_val > 0:
                change_pct = (curr_val - base_val) / base_val * 100
                if change_pct > threshold_pct:
                    regressions.append({
                        "metric": f"latency_{metric}",
                        "baseline": base_val,
                        "current": curr_val,
                        "change_pct": round(change_pct, 2),
                        "threshold_pct": threshold_pct,
                    })

        curr_rps = current.get("metrics", {}).get("requests_per_second", 0)
        base_rps = baseline.get("metrics", {}).get("requests_per_second", 0)
        if base_rps > 0:
            rps_change = (base_rps - curr_rps) / base_rps * 100
            if rps_change > threshold_pct:
                regressions.append({
                    "metric": "throughput",
                    "baseline": base_rps,
                    "current": curr_rps,
                    "change_pct": round(-rps_change, 2),
                    "threshold_pct": threshold_pct,
                })

        return {
            "regression_detected": len(regressions) > 0,
            "regressions": regressions,
            "status": "REGRESSION" if regressions else "STABLE",
        }

    def capacity_model(self, metrics: Dict) -> Dict[str, Any]:
        """Estimate capacity based on observed metrics."""
        rps = metrics.get("requests_per_second", 0)
        p99 = metrics.get("latency", {}).get("p99", 0)
        error_rate = metrics.get("error_rate", 0)

        # Estimate max capacity (where p99 would hit 10s SLO)
        if p99 > 0 and rps > 0:
            headroom = 10.0 / p99  # SLO target / current p99
            estimated_max_rps = rps * headroom * 0.7  # 70% safety margin
        else:
            estimated_max_rps = 0

        # Estimate users
        avg_requests_per_user_per_hour = 10  # Assumption
        max_concurrent_users = estimated_max_rps * 3600 / avg_requests_per_user_per_hour

        return {
            "observed_rps": round(rps, 2),
            "observed_p99": round(p99, 4),
            "estimated_max_rps": round(estimated_max_rps, 2),
            "estimated_max_concurrent_users": int(max_concurrent_users),
            "headroom_multiplier": round(10.0 / p99 if p99 > 0 else 0, 2),
            "recommendation": (
                "Sufficient capacity" if estimated_max_rps > 200
                else "Consider scaling" if estimated_max_rps > 100
                else "Scale immediately"
            ),
        }

    @staticmethod
    def _default_simulator():
        """Simulate STC pipeline latency distribution."""
        # Realistic distribution: PII(20ms) + embed(100ms) + search(30ms) + LLM(1-5s) + Critic(200ms)
        base = 0.35  # Fixed overhead
        llm = random.lognormvariate(0.5, 0.6)  # Log-normal for LLM (heavy tail)
        llm = max(0.5, min(llm, 15.0))  # Clamp 0.5-15s
        total = base + llm

        # 0.5% error rate
        if random.random() < 0.005:
            return (500, total)
        return (200, total)


# ── Demo ────────────────────────────────────────────────────────────────────

def demo():
    print("=" * 70)
    print("STC Performance Testing Framework — Demo")
    print("=" * 70)

    audit_log = []
    runner = PerformanceTestRunner(audit_callback=lambda e: audit_log.append(e))

    # Run baseline test (capped to 10s for demo)
    print("\n▸ Running BASELINE load test (simulated, 10s cap)...")
    baseline = runner.run_load_test(
        LoadProfile.BASELINE,
        config=LoadConfig(LoadProfile.BASELINE, concurrent_users=20,
                          duration_seconds=10, ramp_seconds=2, target_rps=50)
    )

    m = baseline["metrics"]
    print(f"\n  Results:")
    print(f"  Total requests: {m['total_requests']}")
    print(f"  Throughput: {m['requests_per_second']} rps")
    print(f"  Availability: {m['availability']}%")
    print(f"  Error rate: {m['error_rate']}%")
    print(f"  Latency:")
    print(f"    p50: {m['latency']['p50']}s")
    print(f"    p95: {m['latency']['p95']}s")
    print(f"    p99: {m['latency']['p99']}s")
    print(f"    mean: {m['latency']['mean']}s")

    # SLO validation
    print("\n▸ SLO Validation:")
    slo = baseline["slo_validation"]
    print(f"  Overall: {slo['overall']}")
    print(f"  Passed: {slo['slos_passed']}/{slo['slos_evaluated']}")
    for r in slo["results"]:
        icon = "✓" if r["passed"] else ("✗" if r["passed"] is False else "?")
        actual = f"{r['actual']}" if r['actual'] is not None else "N/A"
        print(f"    {icon} {r['slo']}: {actual}{r['unit']} (target: {r['target']}{r['unit']})")

    # Run peak test
    print("\n▸ Running PEAK load test (simulated, 10s cap)...")
    peak = runner.run_load_test(
        LoadProfile.PEAK,
        config=LoadConfig(LoadProfile.PEAK, concurrent_users=50,
                          duration_seconds=10, ramp_seconds=3, target_rps=100)
    )
    pm = peak["metrics"]
    print(f"  Throughput: {pm['requests_per_second']} rps | p99: {pm['latency']['p99']}s | "
          f"Errors: {pm['error_rate']}%")

    # Regression check
    print("\n▸ Regression check (peak vs baseline):")
    regression = runner.regression_check(peak, baseline)
    print(f"  Status: {regression['status']}")
    if regression["regressions"]:
        for r in regression["regressions"]:
            print(f"    ⚠ {r['metric']}: {r['baseline']} → {r['current']} ({r['change_pct']:+.1f}%)")
    else:
        print("    No regressions detected")

    # Capacity model
    print("\n▸ Capacity model (from baseline):")
    cap = runner.capacity_model(m)
    print(f"  Observed: {cap['observed_rps']} rps at p99={cap['observed_p99']}s")
    print(f"  Estimated max: {cap['estimated_max_rps']} rps")
    print(f"  Max concurrent users: ~{cap['estimated_max_concurrent_users']}")
    print(f"  Headroom: {cap['headroom_multiplier']}x")
    print(f"  Recommendation: {cap['recommendation']}")

    # SLO definitions
    print("\n▸ SLO Definitions:")
    for slo in STC_SLOS:
        budget = f", error budget: {slo.error_budget:.4%}" if slo.error_budget else ""
        print(f"  {slo.name}: {slo.target}{slo.unit}{budget}")

    print(f"\n▸ Audit events: {len(audit_log)}")

    print("\n" + "=" * 70)
    print("✓ Performance testing framework demo complete")
    print("=" * 70)


if __name__ == "__main__":
    demo()
