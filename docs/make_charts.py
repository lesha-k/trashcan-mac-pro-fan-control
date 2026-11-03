#!/usr/bin/python3 -I
"""Render the README load-test charts (light and dark SVG) from docs/data/*.csv.

Usage: python3 -I docs/make_charts.py
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))

THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781",
                  grid="#e1e0d9", axis="#c3c2b7", band="#f0efec",
                  core="#2a78d6", prox="#eb6834", fan="#1baf7a"),
    "dark": dict(surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7", muted="#898781",
                 grid="#2c2c2a", axis="#383835", band="#242423",
                 core="#3987e5", prox="#d95926", fan="#199e70"),
}

RUNS = [
    ("stock", "stock.csv", "Stock SMC fan curve",
     "16-thread stage stopped by the 80 °C guard after 255 s"),
    ("with-controller", "with-controller.csv", "With this controller (--base 950)",
     "16-thread stage ran its full 300 s"),
]

W, L, R = 820, 48, 96
T_MAX = 790                      # shared time axis so both charts compare directly
TEMP = (40, 90, 190, 70)         # ymin, ymax, panel height, panel top
FAN = (600, 2100, 100, 300)


def load(name):
    rows = []
    with open(os.path.join(HERE, "data", name)) as f:
        for r in csv.DictReader(f):
            rows.append(dict(t=int(r["t"]), w=int(r["workers"]), core=float(r["core_max"]),
                             prox=float(r["TC0P"]), fan=int(r["fan_target"])))
    return rows


def stages(rows):
    out, seen16 = [], False
    for r in rows:
        seen16 |= r["w"] == 16
        lab = "cooldown" if (r["w"] == 0 and seen16) else ("idle" if r["w"] == 0 else f"{r['w']} threads")
        if not out or out[-1][0] != lab:
            out.append([lab, r["t"], r["t"]])
        out[-1][2] = r["t"]
    return out


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;")


def chart(rows, title, sub, c):
    X = lambda t: L + t / T_MAX * (W - L - R)
    o = []
    a = o.append
    H = FAN[3] + FAN[2] + 30
    a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
      f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" font-size="12">')
    a(f'<title>{esc(title)}: {esc(sub)}</title>')
    a(f'<rect width="{W}" height="{H}" rx="8" fill="{c["surface"]}"/>')
    a(f'<text x="{L}" y="24" font-size="15" font-weight="600" fill="{c["ink"]}">{esc(title)}</text>')
    a(f'<text x="{L}" y="43" fill="{c["ink2"]}">{esc(sub)}</text>')
    # legend
    lx = W - R - 330
    for i, (k, lab) in enumerate([("core", "Hottest CPU core"), ("prox", "SMC CPU proximity (TC0P)")]):
        x = lx + i * 140
        a(f'<line x1="{x}" x2="{x+14}" y1="20" y2="20" stroke="{c[k]}" stroke-width="2" stroke-linecap="round"/>')
        a(f'<text x="{x+20}" y="24" fill="{c["ink2"]}">{lab}</text>')

    st = stages(rows)

    def panel(lo, hi, h, top, keys, ticks, refs, unit, band_labels):
        Y = lambda v: top + (1 - (v - lo) / (hi - lo)) * h
        for i, (lab, t0, t1) in enumerate(st):
            if i % 2:
                a(f'<rect x="{X(t0):.1f}" y="{top}" width="{X(t1)-X(t0):.1f}" height="{h}" fill="{c["band"]}"/>')
            if band_labels:
                a(f'<text x="{X(t0)+4:.1f}" y="{top+h-7}" fill="{c["muted"]}" font-size="11">{lab}</text>')
        for v in ticks:
            a(f'<line x1="{L}" x2="{W-R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{c["grid"]}"/>')
            a(f'<text x="{L-8}" y="{Y(v)+4:.1f}" text-anchor="end" fill="{c["muted"]}" font-size="11">{v}</text>')
        a(f'<text x="{L-8}" y="{top-14}" text-anchor="end" fill="{c["muted"]}" font-size="11">{unit}</text>')
        for v, lab in refs:
            a(f'<line x1="{L}" x2="{W-R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{c["muted"]}" stroke-dasharray="4 3"/>')
            a(f'<text x="{W-R+6}" y="{Y(v)+4:.1f}" fill="{c["muted"]}" font-size="11">{lab}</text>')
        a(f'<line x1="{L}" x2="{W-R}" y1="{top+h}" y2="{top+h}" stroke="{c["axis"]}"/>')
        for k, lab in keys:
            d = "".join(f'{"L" if i else "M"}{X(r["t"]):.1f} {Y(r[k]):.1f}' for i, r in enumerate(rows))
            a(f'<path d="{d}" fill="none" stroke="{c[k]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
            if lab:
                last = rows[-1]
                a(f'<text x="{X(last["t"])+6:.1f}" y="{Y(last[k])+4:.1f}" fill="{c["ink2"]}" font-size="11">{lab}</text>')

    panel(*TEMP, [("core", None), ("prox", None)], [40, 50, 60, 70, 80, 90],
          [(80, "80 °C guard"), (88, "CPU high 88")], "°C", True)
    # peak annotations, in text ink
    load_rows = [r for r in rows if r["w"] == 16]
    pk = max(load_rows, key=lambda r: r["core"])
    Yt = lambda v: TEMP[3] + (1 - (v - TEMP[0]) / (TEMP[1] - TEMP[0])) * TEMP[2]
    a(f'<circle cx="{X(pk["t"]):.1f}" cy="{Yt(pk["core"]):.1f}" r="4" fill="{c["core"]}" stroke="{c["surface"]}" stroke-width="2"/>')
    a(f'<text x="{X(pk["t"]):.1f}" y="{Yt(pk["core"])-10:.1f}" text-anchor="middle" fill="{c["ink"]}" '
      f'font-size="11" font-weight="600">peak {pk["core"]:.0f} °C</text>')

    a(f'<text x="{L}" y="{FAN[3]-12}" fill="{c["ink2"]}" font-size="12">Fan target (SMC), rpm</text>')
    panel(*FAN, [("fan", None)], [800, 1200, 1600, 2000], [(1950, "fan max ~1950")], "", False)
    fl = [r["fan"] for r in load_rows]
    Yf = lambda v: FAN[3] + (1 - (v - FAN[0]) / (FAN[1] - FAN[0])) * FAN[2]
    mid = load_rows[len(load_rows) // 2]
    txt = f"{min(fl)} rpm under load" if min(fl) == max(fl) else f"up to {max(fl)} rpm under load"
    a(f'<text x="{X(mid["t"]):.1f}" y="{Yf(max(fl))-8:.1f}" text-anchor="middle" fill="{c["ink"]}" '
      f'font-size="11" font-weight="600">{txt}</text>')
    for m in range(0, T_MAX // 60 + 1):
        x = X(m * 60)
        a(f'<text x="{x:.1f}" y="{FAN[3]+FAN[2]+18}" text-anchor="middle" fill="{c["muted"]}" font-size="11">{m}</text>')
    a(f'<text x="{W-R+6}" y="{FAN[3]+FAN[2]+18}" fill="{c["muted"]}" font-size="11">min</text>')
    a("</svg>")
    return "\n".join(o) + "\n"


def main():
    for key, fn, title, sub in RUNS:
        rows = load(fn)
        for theme, c in THEMES.items():
            path = os.path.join(HERE, f"{key}-{theme}.svg")
            with open(path, "w") as f:
                f.write(chart(rows, title, sub, c))
            print(path)


if __name__ == "__main__":
    main()
