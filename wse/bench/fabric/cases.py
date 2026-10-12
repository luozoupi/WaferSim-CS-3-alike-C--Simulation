#!/usr/bin/env python3
"""Stage 1 / M1 fabric microbenchmark cases (fixed before any run; PREREGISTRATION.md).
Each case is a dict: family, role 'train' | 'holdout', and family parameters.  Directions: E, W, N, S.
Families switch-advance and teardown were added by Addendum A (2026-09-26) before they were run."""


def straight():
    out = []
    for d in ("E", "W"):
        for h in (1, 2, 4, 8, 16, 32, 64, 128):
            for B in (1, 8, 64, 256, 512):
                hold = (h in (8, 128)) or (B == 256)
                out.append(dict(family="straight", dir=d, hops=h, B=B, role="holdout" if hold else "train"))
    for d in ("N", "S"):
        for h in (1, 4, 8, 16, 64, 128):
            for B in (8, 256, 512):
                hold = (h in (8, 128)) or (B == 256)
                out.append(dict(family="straight", dir=d, hops=h, B=B, role="holdout" if hold else "train"))
    return out


def turns():
    out = []
    for d1, d2 in (("E", "N"), ("E", "S"), ("W", "N"), ("W", "S"), ("N", "E"), ("N", "W"), ("S", "E"), ("S", "W")):
        for a, b in ((1, 1), (4, 4), (16, 16), (4, 16), (8, 8), (16, 4)):
            hold = (a, b) in ((8, 8), (16, 4))
            out.append(dict(family="turn", d1=d1, d2=d2, a=a, b=b, B=64, role="holdout" if hold else "train"))
        out.append(dict(family="turn", d1=d1, d2=d2, a=8, b=8, B=512, role="holdout"))
    return out


def multicast():
    out = []
    for L in (16, 24, 32):
        for f in (2, 4, 6, 8):
            if L % f:
                continue
            for B in (64, 512):
                hold = (L == 24) or (f == 6)
                out.append(dict(family="multicast", L=L, fanout=f, B=B, role="holdout" if hold else "train"))
    return out


def contention():
    out = []
    for k in (1, 2, 3, 4):                      # k sources on one row, distinct colours, merging eastwards
        for B in (64, 256, 512):
            hold = (k == 3) or (B == 256)
            out.append(dict(family="contention", k=k, gap=4, tail=8, B=B, role="holdout" if hold else "train"))
    return out


def relay():
    out = []
    for N in (1, 2, 4, 6, 8):
        for B in (8, 64, 256, 512):
            hold = (N == 6) or (B == 256)
            out.append(dict(family="relay", N=N, B=B, role="holdout" if hold else "train"))
    return out


def backpressure():
    out = []
    for h in (1, 4, 8, 16):
        for B in (64, 512):
            for D in (0, 16, 64, 128, 256, 1024):
                hold = (h == 8) or (D == 128)
                out.append(dict(family="backpressure", hops=h, B=B, delay=D, role="holdout" if hold else "train"))
    return out


# ---- Addendum A (2026-09-26, PREREGISTRATION.md): switch-advance and teardown families, fixed before any run ----
def sa_tx():
    """tx-side switch mid-path: sender at 0, tile m pos0 W->R (B1 to PE m), pos1 tx E; ctrl ADVANCE(no_ce); B2 to L=2m"""
    out = []
    for m in (1, 4, 8, 16):
        for B1 in (1, 64):
            for B2 in (64, 512):
                out.append(dict(family="sa_tx", m=m, B1=B1, B2=B2, role="holdout" if m == 8 else "train"))
    return out


def sa_rx():
    """rx-side switch at a middle root (gather idiom): left sender B then ctrl ADVANCE; right sender B, held until
    the root's input flips from W to E"""
    return [dict(family="sa_rx", m=m, B=B, role="holdout" if m == 4 else "train") for m in (1, 4, 8) for B in (8, 64, 512)]


def sa_chain():
    """gather chain: N senders, each pos0 R->E, pos1 rx W, sending B with .advance_switch; root at N receives N*B"""
    return [dict(family="sa_chain", N=N, B=B, role="holdout" if N == 8 else "train") for N in (2, 4, 8, 12) for B in (1, 8, 64, 256)]


def sa_ring():
    """topic-06 replica with timing: centre of 3x3 sends [ctrl ADVANCE, B data] x 4 through ring-mode positions"""
    return [dict(family="sa_ring", B=B, role="holdout" if B == 64 else "train") for B in (1, 16, 64, 256)]


def td_line():
    """teardown: sender B data then TEARDOWN(no_ce) along L hops (tiles tx {R, E}); each PE's teardown handler
    injects a marker, exits teardown; phase 2 (P2 > 0): sender sends P2 more, every receiver receives them"""
    return [dict(family="td_line", L=L, B=B, P2=P2, role="holdout" if L == 8 else "train")
            for L in (1, 4, 8, 16) for B in (1, 64) for P2 in (0, 64)]


def addendum_a():
    return sa_tx() + sa_rx() + sa_chain() + sa_ring() + td_line()


def all_cases():
    return straight() + turns() + multicast() + contention() + relay() + backpressure() + addendum_a()


def tag(c):
    f = c["family"]
    if f == "straight":
        return f"straight_{c['dir']}_h{c['hops']}_B{c['B']}"
    if f == "turn":
        return f"turn_{c['d1']}{c['d2']}_a{c['a']}_b{c['b']}_B{c['B']}"
    if f == "multicast":
        return f"mcast_L{c['L']}_f{c['fanout']}_B{c['B']}"
    if f == "contention":
        return f"cont_k{c['k']}_B{c['B']}"
    if f == "relay":
        return f"relay_N{c['N']}_B{c['B']}"
    if f == "sa_tx":
        return f"satx_m{c['m']}_B{c['B1']}_{c['B2']}"
    if f == "sa_rx":
        return f"sarx_m{c['m']}_B{c['B']}"
    if f == "sa_chain":
        return f"sachain_N{c['N']}_B{c['B']}"
    if f == "sa_ring":
        return f"saring_B{c['B']}"
    if f == "td_line":
        return f"td_L{c['L']}_B{c['B']}_P{c['P2']}"
    return f"bp_h{c['hops']}_B{c['B']}_D{c['delay']}"


if __name__ == "__main__":
    cs = all_cases()
    from collections import Counter
    print(len(cs), "cases;", Counter((c["family"], c["role"]) for c in cs))
