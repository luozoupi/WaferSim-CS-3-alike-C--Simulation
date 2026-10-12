"""Stage 1 calibration sets (Addendum D: P = 12; Addendum E: P = 40): x-dimension lines, disjoint from every gate set,
one row each.  P from env CAL_P (default 12)."""
import os
P = int(os.environ.get("CAL_P", "12"))
ROOTS = {12: (0, 5, 11), 40: (0, 20, 39)}[P]
OPS = {0: "bcast", 1: "scatter", 2: "gather", 3: "reduce"}


def rows():
    out = []
    for op in OPS:
        for root in ROOTS:
            for cnt in (4, 24):
                out.append(dict(op=op, root=root, count=cnt, reps=1))
    for op in OPS:
        out.append(dict(op=op, root=0, count=4, reps=2))
    return out


def tag(r):
    return f"cal_{OPS[r['op']]}_P{P}_c{r['count']}_r{r['root']}_x{r['reps']}"
