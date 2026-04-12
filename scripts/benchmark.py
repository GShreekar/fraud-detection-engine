"""
Benchmark script for the Fraud Detection Engine.

Measures API throughput, per-request latency (p50/p95/p99), and error rate
under configurable concurrency levels.

Usage:
    # Ensure the Docker Compose stack is running first:
    #   docker compose -f docker/docker-compose.yml up -d
    #
    # Then run the benchmark:
    python scripts/benchmark.py

    # With custom settings:
    python scripts/benchmark.py --requests 500 --concurrency 10 --base-url http://localhost:8000

Output:
    - Console summary with latency percentiles and throughput
    - JSON results file at scripts/benchmark_results.json
"""

import argparse
import asyncio
import json
import random
import statistics
import time
from pathlib import Path

import httpx

# --- Transaction generators ---

COUNTRIES_CLEAN = ["US", "GB", "DE", "FR", "JP", "AU", "CA"]
COUNTRIES_RISKY = ["NG", "KP", "IR", "SY"]
MERCHANTS = [f"merchant_{i}" for i in range(1, 20)]
USERS = [f"user_{i}" for i in range(1, 50)]
DEVICES = [f"device_{i}" for i in range(1, 30)]
IPS = [f"10.0.{i // 256}.{i % 256}" for i in range(1, 100)]

API_PATH = "/api/v1/transactions/analyze"


def _random_transaction(index: int) -> dict:
    """Generate a randomised transaction payload."""
    is_risky = random.random() < 0.3
    return {
        "transaction_id": f"bench_txn_{index:06d}",
        "user_id": random.choice(USERS),
        "amount": round(random.uniform(10, 5000), 2) if is_risky else round(random.uniform(5, 500), 2),
        "merchant_id": random.choice(MERCHANTS),
        "device_id": random.choice(DEVICES[:5]) if is_risky else random.choice(DEVICES),
        "ip_address": random.choice(IPS[:5]) if is_risky else random.choice(IPS),
        "country": random.choice(COUNTRIES_RISKY) if is_risky else random.choice(COUNTRIES_CLEAN),
        "account_age_days": random.choice([5, 10, 15]) if is_risky else random.choice([60, 120, 365]),
        "merchant_category": random.choice(["crypto", "gambling"]) if is_risky else "electronics",
    }


async def _send_request(client: httpx.AsyncClient, base_url: str, payload: dict) -> dict:
    """Send a single request and return timing + result info."""
    url = f"{base_url}{API_PATH}"
    start = time.perf_counter()
    try:
        resp = await client.post(url, json=payload, timeout=30.0)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "status": resp.status_code,
            "latency_ms": round(elapsed_ms, 2),
            "decision": resp.json().get("decision") if resp.status_code == 200 else None,
            "error": None,
        }
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "status": 0,
            "latency_ms": round(elapsed_ms, 2),
            "decision": None,
            "error": str(exc),
        }


async def _run_batch(base_url: str, payloads: list[dict], concurrency: int) -> list[dict]:
    """Run a batch of requests with bounded concurrency."""
    semaphore = asyncio.Semaphore(concurrency)
    results = []

    async with httpx.AsyncClient() as client:
        async def _bounded(payload):
            async with semaphore:
                return await _send_request(client, base_url, payload)

        results = await asyncio.gather(*[_bounded(p) for p in payloads])

    return list(results)


def _percentile(data: list[float], pct: float) -> float:
    """Calculate a percentile from a sorted list."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (pct / 100)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_data) else f
    d = k - f
    return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])


def _print_report(results: list[dict], total_time: float, concurrency: int):
    """Print a formatted benchmark report."""
    latencies = [r["latency_ms"] for r in results if r["status"] == 200]
    errors = [r for r in results if r["status"] != 200]
    decisions = {}
    for r in results:
        if r["decision"]:
            decisions[r["decision"]] = decisions.get(r["decision"], 0) + 1

    print("\n" + "=" * 60)
    print("FRAUD DETECTION ENGINE — BENCHMARK RESULTS")
    print("=" * 60)
    print(f"Total requests:     {len(results)}")
    print(f"Concurrency:        {concurrency}")
    print(f"Total wall time:    {total_time:.2f}s")
    print(f"Throughput:         {len(results) / total_time:.1f} req/s")
    print(f"Errors:             {len(errors)}")
    print(f"Error rate:         {len(errors) / len(results) * 100:.1f}%")
    print("-" * 60)

    if latencies:
        print(f"Latency p50:        {_percentile(latencies, 50):.2f}ms")
        print(f"Latency p95:        {_percentile(latencies, 95):.2f}ms")
        print(f"Latency p99:        {_percentile(latencies, 99):.2f}ms")
        print(f"Latency min:        {min(latencies):.2f}ms")
        print(f"Latency max:        {max(latencies):.2f}ms")
        print(f"Latency mean:       {statistics.mean(latencies):.2f}ms")
        print(f"Latency stddev:     {statistics.stdev(latencies):.2f}ms" if len(latencies) > 1 else "")

    print("-" * 60)
    print("Decision distribution:")
    for decision, count in sorted(decisions.items()):
        print(f"  {decision:10s}  {count:5d}  ({count / len(results) * 100:.1f}%)")
    print("=" * 60)


def _save_results(results: list[dict], total_time: float, concurrency: int, output_path: str):
    """Save benchmark results to JSON."""
    latencies = [r["latency_ms"] for r in results if r["status"] == 200]
    summary = {
        "total_requests": len(results),
        "concurrency": concurrency,
        "total_time_seconds": round(total_time, 2),
        "throughput_rps": round(len(results) / total_time, 1),
        "error_count": sum(1 for r in results if r["status"] != 200),
        "latency_p50_ms": round(_percentile(latencies, 50), 2) if latencies else None,
        "latency_p95_ms": round(_percentile(latencies, 95), 2) if latencies else None,
        "latency_p99_ms": round(_percentile(latencies, 99), 2) if latencies else None,
        "latency_min_ms": round(min(latencies), 2) if latencies else None,
        "latency_max_ms": round(max(latencies), 2) if latencies else None,
        "latency_mean_ms": round(statistics.mean(latencies), 2) if latencies else None,
    }

    with open(output_path, "w") as f:
        json.dump({"summary": summary, "raw_results": results}, f, indent=2)

    print(f"\nResults saved to {output_path}")


async def main():
    parser = argparse.ArgumentParser(description="Benchmark the Fraud Detection Engine API")
    parser.add_argument("--requests", type=int, default=1000, help="Total number of requests")
    parser.add_argument("--concurrency", type=int, default=5, help="Max concurrent requests")
    parser.add_argument("--base-url", type=str, default="http://localhost:8000", help="API base URL")
    parser.add_argument("--output", type=str, default="scripts/benchmark_results.json", help="Output file")
    args = parser.parse_args()

    print(f"Generating {args.requests} test transactions...")
    payloads = [_random_transaction(i) for i in range(args.requests)]

    print(f"Running benchmark: {args.requests} requests, concurrency={args.concurrency}")
    start = time.perf_counter()
    results = await _run_batch(args.base_url, payloads, args.concurrency)
    total_time = time.perf_counter() - start

    _print_report(results, total_time, args.concurrency)
    _save_results(results, total_time, args.concurrency, args.output)


if __name__ == "__main__":
    asyncio.run(main())
