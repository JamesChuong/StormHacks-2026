"""Generate challenges/*.json: hidden tests come from random inputs run through a reference solution.

Usage: python scripts/gen_challenges.py
"""
import json
import random
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "challenges"


def run_ref(code, stdin):
    return subprocess.run([sys.executable, "-c", code], input=stdin, capture_output=True,
                          text=True, check=True, timeout=30).stdout.strip()


def ints(xs):
    return " ".join(map(str, xs))


# --------------------------------------------------------------------------

MAX_SUBARRAY = {
    "id": "max-subarray",
    "title": "Maximum Subarray Sum",
    "statement": (
        "Given an array of n integers, print the largest possible sum of a non-empty "
        "contiguous subarray.\n\nInput: the first line has n (1 <= n <= 5*10^4). The second "
        "line has n integers a_i (-10^9 <= a_i <= 10^9).\n\nOutput: a single integer."),
    "reference_solution": (
        "import sys\n"
        "def main():\n"
        "    data = sys.stdin.read().split()\n"
        "    n = int(data[0])\n"
        "    best = cur = int(data[1])\n"
        "    for x in map(int, data[2:n + 1]):\n"
        "        cur = max(x, cur + x)\n"
        "        best = max(best, cur)\n"
        "    print(best)\n"
        "main()\n"),
    "examples": ["5\n1 -2 3 4 -1", "3\n-5 -1 -3"],
    "gen": [
        lambda rng: "1\n-7",
        lambda rng: "4\n0 0 0 0",
        lambda rng: "5\n-1000000000 -1000000000 -1000000000 -1000000000 -1",
        lambda rng: "6\n1000000000 1000000000 1000000000 -1 1000000000 1000000000",
        *[lambda rng, n=n: f"{n}\n{ints(rng.randint(-100, 100) for _ in range(n))}"
          for n in (10, 50, 200, 1000)],
        lambda rng: f"50000\n{ints(rng.randint(-10**9, 10**9) for _ in range(50000))}",
        lambda rng: f"50000\n{ints(rng.randint(-5, 3) for _ in range(50000))}",
    ],
}

PAIR_SUM = {
    "id": "pair-sum-count",
    "title": "Count Pairs With Target Sum",
    "statement": (
        "Given n integers and a target k, count the pairs of indices i < j with "
        "a_i + a_j = k.\n\nInput: the first line has n and k (1 <= n <= 5*10^4, "
        "|k| <= 2*10^9). The second line has n integers (|a_i| <= 10^9).\n\n"
        "Output: the number of pairs (it may not fit in 32 bits)."),
    "reference_solution": (
        "import sys\n"
        "from collections import Counter\n"
        "def main():\n"
        "    data = sys.stdin.read().split()\n"
        "    n, k = int(data[0]), int(data[1])\n"
        "    seen = Counter()\n"
        "    total = 0\n"
        "    for x in map(int, data[2:2 + n]):\n"
        "        total += seen[k - x]\n"
        "        seen[x] += 1\n"
        "    print(total)\n"
        "main()\n"),
    "examples": ["5 6\n1 5 3 3 7", "4 0\n-2 2 0 0"],
    "gen": [
        lambda rng: "1 2\n1",
        lambda rng: "6 4\n2 2 2 2 2 2",
        lambda rng: "4 -3\n-1 -2 -5 2",
        *[lambda rng, n=n: f"{n} {rng.randint(-10, 10)}\n{ints(rng.randint(-10, 10) for _ in range(n))}"
          for n in (10, 100, 1000)],
        lambda rng: f"50000 0\n{ints([0] * 50000)}",
        lambda rng: f"50000 7\n{ints(rng.randint(-10**9, 10**9) for _ in range(50000))}",
        lambda rng: f"50000 10\n{ints(rng.randint(0, 10) for _ in range(50000))}",
    ],
}

LONGEST_UNIQUE = {
    "id": "longest-unique-substring",
    "title": "Longest Substring Without Repeats",
    "statement": (
        "Given a string s of lowercase letters, print the length of the longest substring "
        "that contains no repeated character.\n\nInput: one line with s "
        "(0 <= |s| <= 5*10^4). The line may be empty.\n\nOutput: a single integer."),
    "reference_solution": (
        "import sys\n"
        "def main():\n"
        "    s = sys.stdin.readline().strip()\n"
        "    last = {}\n"
        "    best = start = 0\n"
        "    for i, c in enumerate(s):\n"
        "        if last.get(c, -1) >= start:\n"
        "            start = last[c] + 1\n"
        "        last[c] = i\n"
        "        best = max(best, i - start + 1)\n"
        "    print(best)\n"
        "main()\n"),
    "examples": ["abcabcbb", "bbbbb"],
    "gen": [
        lambda rng: "",
        lambda rng: "a",
        lambda rng: "abcdefghijklmnopqrstuvwxyz",
        lambda rng: "abba",
        *[lambda rng, n=n: "".join(rng.choice("abcde") for _ in range(n)) for n in (10, 100, 1000)],
        lambda rng: "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(50000)),
        lambda rng: "ab" * 25000,
    ],
}


def build(spec, rng):
    ref = spec["reference_solution"]
    return {
        "id": spec["id"],
        "title": spec["title"],
        "statement": spec["statement"],
        "examples": [{"input": i, "output": run_ref(ref, i)} for i in spec["examples"]],
        "hidden_tests": [{"input": (i := g(rng)), "output": run_ref(ref, i)} for g in spec["gen"]],
        "time_limit_s": 90,
        "run_timeout_ms": 3000,
        "memory_limit_mb": 256,
        "languages": ["python"],
        "reference_solution": ref,
    }


if __name__ == "__main__":
    rng = random.Random(2026)
    OUT.mkdir(exist_ok=True)
    for spec in (MAX_SUBARRAY, PAIR_SUM, LONGEST_UNIQUE):
        path = OUT / f"{spec['id']}.json"
        path.write_text(json.dumps(build(spec, rng), indent=1))
        print("wrote", path)
