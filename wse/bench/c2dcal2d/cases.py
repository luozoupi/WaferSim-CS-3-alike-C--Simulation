"""Stage 1 Addendum G calibration set: 24 x 24 grid, both modules initialised; configuration k = (op, root, count)."""
P = 24
OPS = {0: "bcast", 1: "scatter", 2: "gather", 3: "reduce"}


def configs():
    return [dict(op=op, root=root, count=cnt) for op in OPS for root in (0, 12, 23) for cnt in (4, 24)]


def tag(c):
    return f"{OPS[c['op']]}_r{c['root']}_c{c['count']}"
