#!/usr/bin/env python
"""(a) Planning layer: plan every scenario of the five paper domains with GTPyhop.

    python scripts/run_planning.py

Prints plan lengths and exits non-zero if any differs from the value reported
in the paper (drug target discovery 8 x 3; PCR 31 + 6n + 2(ceil(n/40) - 1)
for n = 4..96; Omega HDQ 129/91/89; TNF 12; cross-server 9/15).
"""

import sys

import _bootstrap  # noqa: F401
from hplan_orchestrator import planning


def main() -> int:
    print(f"gtpyhop {planning.gtpyhop_version()}\n")
    print(f"{'domain':<40} {'scenario':<28} {'plan':>5} {'paper':>6}  {'bound':<6} ok")
    print("-" * 94)
    bad = 0
    seen = set()
    for r in planning.plan_all():
        seen.add((r.domain, r.problem))
        exp = planning.EXPECTED_LENGTHS[r.domain].get(r.problem)
        ok = r.length is not None and r.length == exp
        bad += not ok
        bound = "yes" if planning.DOMAINS[r.domain] else "no"
        note = f"  (n={planning.PCR_SAMPLES[r.problem]})" if r.domain == "bio_opentrons" else ""
        print(f"{r.domain:<40} {r.problem:<28} {str(r.length):>5} {str(exp):>6}  {bound:<6} "
              f"{'OK' if ok else 'MISMATCH'}{note}")
    for d, probs in planning.EXPECTED_LENGTHS.items():
        for p in probs:
            if (d, p) not in seen:
                bad += 1
                print(f"{d:<40} {p:<28} {'-':>5} {probs[p]:>6}  MISSING from gtpyhop-examples")
    expected_total = sum(len(v) for v in planning.EXPECTED_LENGTHS.values())
    print("-" * 94)
    print(f"{expected_total - bad}/{expected_total} scenarios match the paper"
          + ("" if not bad else f"; {bad} MISMATCH"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
