#!/usr/bin/env python3
"""
0x004 · activity — regenerates the live telemetry section of portfolio.svg.

Two unauthenticated requests:
  · github.com/users/<user>/contributions   → 12-month calendar (no API quota)
  · api.github.com/users/<user>/repos       → repo list for the language mix

    python3 scripts/activity.py              # fetch + splice
    python3 scripts/activity.py --dry-run    # render 0x004-activity.svg only

The section is inserted directly after $stack and before $contact, and every
section index is renumbered from document order, so nothing drifts.

Future-dated cells are discarded. GitHub pads the trailing week of the calendar
with days that have not happened yet; counting them would understate the
active-day ratio and silently extend the grid past today.

On any fetch failure the existing section is left exactly as it was, so a
network blip or a GitHub markup change can never blank the page.
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, re, sys, urllib.request
from collections import Counter

USER    = os.environ.get("GH_USER", "natishmourani")
SVG     = os.environ.get("PORTFOLIO_SVG", "portfolio.svg")
SECTION = "0x004-activity.svg"
TOKEN   = os.environ.get("GITHUB_TOKEN", "")

# ── design tokens, shared with the rest of the document ───────────────────
W, M        = 1100, 64
H           = 0                       # set below, once geometry is known
BG, PANEL   = "#0d1117", "#080b10"   # GitHub dark canvas + recessed panel
RULE, BONE  = "#242c36", "#e8ecf1"
MUTED, BLUE = "#5c6672", "#9ecbff"
AMBER       = "#f0a202"
EMPTY       = "#1a1f28"               # unfilled bar track
VEL_WEEKS   = 26

# Calendar block geometry lives at module level so the section height can be
# derived from real content instead of a hand-tuned constant that goes stale.
SUB_Y       = 124                             # sub-header baseline
SUB_RULE    = SUB_Y + 10
PT          = SUB_RULE + 18                   # panel row top
PB          = PT + 200                        # panel row bottom
STAT_RULE   = PB + 34                         # divider under the panel row
STAT_LABEL  = STAT_RULE + 24
STAT_VALUE  = STAT_LABEL + 25
BOTTOM_PAD  = 30                              # matches the other sections
H           = STAT_VALUE + BOTTOM_PAD # section ends under the stats row
CAP_ADV     = 11 * 0.6 + 2.2          # cap advance including .2em tracking
CAP_S_FS    = 9.5                     # small caps for the narrow stat column
CAP_S_ADV   = CAP_S_FS * 0.6 + 1.9

def esc(s):  return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
def r1(v):   return round(v, 1)

def pin(t, x, y, fs, fill, weight=400, anchor="start"):
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return (f'<text x="{r1(x)}" y="{r1(y)}" font-size="{fs}" font-weight="{weight}" '
            f'fill="{fill}"{a} textLength="{r1(len(t)*fs*0.6)}" '
            f'lengthAdjust="spacingAndGlyphs">{esc(t)}</text>')

def cap(t, x, y, fill, anchor="start"):
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return (f'<text x="{r1(x)}" y="{r1(y)}" class="cap" fill="{fill}"{a} '
            f'textLength="{r1(len(t)*CAP_ADV)}" lengthAdjust="spacing">{esc(t)}</text>')

def cap_s(t, x, y, fill):
    return (f'<text x="{r1(x)}" y="{r1(y)}" font-size="{CAP_S_FS}" font-weight="700" '
            f'letter-spacing=".18em" fill="{fill}" textLength="{r1(len(t)*CAP_S_ADV)}" '
            f'lengthAdjust="spacing">{esc(t)}</text>')

def pulse(cx, cy, colour, r=4, to=12, dur="2s"):
    """Solid dot plus an expanding ring — the same motion as the contact status dot."""
    return (f'<g><circle cx="{r1(cx)}" cy="{r1(cy)}" r="{r}" fill="{colour}"/>'
            f'<circle cx="{r1(cx)}" cy="{r1(cy)}" r="{r}" fill="none" stroke="{colour}" '
            f'stroke-width="1.2">'
            f'<animate attributeName="r" values="{r};{to}" dur="{dur}" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values="0.8;0" dur="{dur}" repeatCount="indefinite"/>'
            f'</circle></g>')

def get(url, accept="text/html"):
    hdr = {"User-Agent": f"{USER}-profile-activity", "Accept": accept,
           "X-Requested-With": "XMLHttpRequest"}
    if TOKEN and "api.github.com" in url:
        hdr["Authorization"] = f"Bearer {TOKEN}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=30) as r:
        return r.read().decode("utf-8", "replace")

# ── fetch ─────────────────────────────────────────────────────────────────
def fetch_calendar():
    html = get(f"https://github.com/users/{USER}/contributions")
    tds = re.findall(
        r'<td[^>]*data-date="(\d{4}-\d{2}-\d{2})"[^>]*id="([^"]+)"[^>]*data-level="(\d)"', html)
    if not tds:
        tds = []
        for tag in re.findall(r'<td[^>]*ContributionCalendar-day[^>]*>', html):
            d = re.search(r'data-date="([\d-]+)"', tag)
            i = re.search(r'id="([^"]+)"', tag)
            l = re.search(r'data-level="(\d)"', tag)
            if d and i and l:
                tds.append((d.group(1), i.group(1), l.group(1)))
    if not tds:
        raise RuntimeError("no contribution cells — GitHub markup may have changed")
    tips = dict(re.findall(r'<tool-tip[^>]*for="([^"]+)"[^>]*>([^<]*)</tool-tip>', html))

    def n(t):
        if not t or t.strip().lower().startswith("no"):
            return 0
        m = re.match(r"\s*(\d+)", t)
        return int(m.group(1)) if m else 0

    days = [{"d": d, "l": int(l), "c": n(tips.get(i, ""))} for d, i, l in tds]
    days.sort(key=lambda x: x["d"])

    # Drop days that have not happened yet. GitHub pads the trailing week.
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    kept = [x for x in days if x["d"] <= today]
    dropped = len(days) - len(kept)
    if not kept:
        raise RuntimeError("calendar contained no elapsed days")
    return kept, dropped

def fetch_repos():
    """Primary language per repository.

    Deliberately NOT the /languages byte counts: those are dominated by Flask
    templates and notebook JSON, which would report this account as mostly
    HTML. Repo count is the honest summary of what actually gets built.
    """
    cache = os.environ.get("REPOS_JSON")           # offline/dev override
    if cache and os.path.exists(cache):
        data = json.load(open(cache))
    else:
        data = json.loads(get(
            f"https://api.github.com/users/{USER}/repos?per_page=100&sort=pushed",
            accept="application/vnd.github+json"))
    if isinstance(data, dict):
        raise RuntimeError(data.get("message", "repo fetch failed"))
    own = [r for r in data if not r.get("fork")]
    if not own:
        raise RuntimeError("no non-fork repositories returned")
    langs = Counter(r["language"] for r in own if r.get("language"))
    return {"count": len(own), "langs": langs.most_common(6)}

# ── stats ─────────────────────────────────────────────────────────────────
def summarise(days):
    total  = sum(x["c"] for x in days)
    active = sum(1 for x in days if x["c"] > 0)
    last   = dt.date.fromisoformat(days[-1]["d"])
    current = 0
    for x in reversed(days):
        if x["c"] > 0:
            current += 1
        elif dt.date.fromisoformat(x["d"]) != last:
            break
    longest = run = 0
    for x in days:
        run = run + 1 if x["c"] > 0 else 0
        longest = max(longest, run)
    recent = [x for x in days if x["c"] > 0]
    weeks = [sum(d["c"] for d in days[i:i + 7]) for i in range(0, len(days), 7)]
    return {"total": total, "active": active, "current": current, "longest": longest,
            "busiest": max(days, key=lambda x: x["c"]),
            "last_active": recent[-1]["d"] if recent else None,
            "weeks": weeks, "to": days[-1]["d"], "span": len(days)}

def ago(iso, today):
    if not iso:
        return "—"
    n = (today - dt.date.fromisoformat(iso)).days
    return "today" if n == 0 else ("yesterday" if n == 1 else f"{n} days ago")

# ── render ────────────────────────────────────────────────────────────────
def render(days, s, repos, stamp, index="0x004"):
    b, today = [], dt.date.fromisoformat(s["to"])
    warn = []

    b.append(pin(index, M, 76, 46, BONE, 300))
    b.append(f'<text x="220" y="64" class="cap" fill="{AMBER}">$</text>')
    b.append(cap("ACTIVITY", 228.8, 64, BONE))
    b.append(f'<text x="{W-M}" y="64" class="path" fill="{MUTED}" text-anchor="end">'
             f'~/{index}-activity</text>')
    b.append(f'<line x1="330" y1="60" x2="{W-M-116}" y2="60" stroke="{RULE}"/>')

    b.append(cap("TELEMETRY — WHAT THE HANDS ARE DOING", M, SUB_Y, BLUE))
    b.append(cap("FIG. 004", W - M, SUB_Y, MUTED, anchor="end"))
    b.append(f'<line x1="{M}" y1="{SUB_RULE}" x2="{W-M}" y2="{SUB_RULE}" stroke="{RULE}"/>')

    A, B_, C = M, 397, 730              # language · velocity · headline figures
    PW = 306

    # ── panel A · language by repository ───────────────────────────────
    b.append(f'<rect x="{A}" y="{PT}" width="{PW}" height="{PB-PT}" rx="3" '
             f'fill="{PANEL}" stroke="{RULE}"/>')
    b.append(cap("LANGUAGE BY REPOSITORY", A + 20, PT + 28, MUTED))
    b.append(f'<line x1="{A+20}" y1="{PT+40}" x2="{A+PW-20}" y2="{PT+40}" stroke="{RULE}"/>')

    langs = [(n.lower(), c) for n, c in repos["langs"]]
    LFS   = 11.5
    lbl_x = A + 20
    cnt_x = A + PW - 20
    MIN_BAR = 70

    # The label column is measured, not guessed — "jupyter notebook" is wider
    # than a fixed gutter allows, and would run under the bar.
    def layout(names):
        wmax = max((len(n) * LFS * 0.6 for n in names), default=0)
        x0 = lbl_x + wmax + 14
        return x0, (cnt_x - 26) - x0

    names = [n for n, _ in langs]
    bar0, barw = layout(names)
    while barw < MIN_BAR and max(len(n) for n in names) > 8:      # trim only if forced
        cutf = max(len(n) for n in names) - 1
        names = [(n[:cutf - 1] + "…") if len(n) > cutf else n for n in names]
        bar0, barw = layout(names)
    langs = list(zip(names, [c for _, c in langs]))

    mx = max((c for _, c in langs), default=1)
    for i, (name, cnt) in enumerate(langs):
        y = PT + 68 + i * 23
        top = i == 0
        b.append(pin(name, lbl_x, y + 4, LFS, BONE if top else MUTED))
        b.append(f'<rect x="{r1(bar0)}" y="{y-6}" width="{r1(barw)}" height="9" rx="1.5" '
                 f'fill="{EMPTY}"/>')
        b.append(f'<rect x="{r1(bar0)}" y="{y-6}" width="{r1(barw*cnt/mx)}" height="9" rx="1.5" '
                 f'fill="{AMBER if top else BLUE}" opacity="{1 if top else .62}"/>')
        b.append(pin(str(cnt), cnt_x, y + 4, LFS, BONE if top else MUTED, anchor="end"))
        if lbl_x + len(name) * LFS * 0.6 > bar0 - 2:
            warn.append(f"language label '{name}' reaches the bar")

    # ── panel B · contribution velocity ────────────────────────────────
    b.append(f'<rect x="{B_}" y="{PT}" width="{PW}" height="{PB-PT}" rx="3" '
             f'fill="{PANEL}" stroke="{RULE}"/>')
    b.append(cap(f"CONTRIBUTION VELOCITY · {VEL_WEEKS}W", B_ + 20, PT + 28, MUTED))
    b.append(f'<line x1="{B_+20}" y1="{PT+40}" x2="{B_+PW-20}" y2="{PT+40}" stroke="{RULE}"/>')

    wk = s["weeks"][-VEL_WEEKS:] or [0]
    cx0, cy0, cw, ch = B_ + 26, PT + 62, PW - 52, 96
    peak = max(wk) or 1
    pts = [(cx0 + i * cw / max(len(wk) - 1, 1), cy0 + ch - v / peak * ch)
           for i, v in enumerate(wk)]
    for f in (0, .5, 1):
        gy = cy0 + ch * f
        b.append(f'<line x1="{cx0}" y1="{r1(gy)}" x2="{r1(cx0+cw)}" y2="{r1(gy)}" '
                 f'stroke="{RULE}" stroke-dasharray="2 4"/>')
    area = (f'M {r1(pts[0][0])} {r1(cy0+ch)} ' +
            " ".join(f"L {r1(x)} {r1(y)}" for x, y in pts) +
            f' L {r1(pts[-1][0])} {r1(cy0+ch)} Z')
    b.append(f'<path d="{area}" fill="{BLUE}" fill-opacity=".10"/>')
    b.append(f'<polyline points="{" ".join(f"{r1(x)},{r1(y)}" for x,y in pts)}" '
             f'fill="none" stroke="{BLUE}" stroke-width="1.6" '
             f'stroke-linejoin="round" stroke-linecap="round"/>')
    b.append(f'<line x1="{cx0}" y1="{r1(cy0+ch)}" x2="{r1(cx0+cw)}" y2="{r1(cy0+ch)}" '
             f'stroke="{MUTED}"/>')

    # peak marker: pulsing, matching the contact status dot. No caption.
    pi = wk.index(peak)
    b.append(pulse(pts[pi][0], pts[pi][1], AMBER, r=3.4, to=11, dur="2s"))

    n_lab = max(len(days) - VEL_WEEKS * 7, 0)
    d0 = dt.date.fromisoformat(days[n_lab]["d"])
    b.append(pin(d0.strftime("%b '%y").lower(), cx0, cy0 + ch + 16, 10, MUTED))
    b.append(pin(today.strftime("%b '%y").lower(), cx0 + cw, cy0 + ch + 16, 10, MUTED,
                 anchor="end"))
    trend = sum(wk[-6:]) - sum(wk[-12:-6])
    word = "accelerating" if trend > 0 else ("steady" if trend == 0 else "cooling")
    b.append(pin(f"trend — {word}", cx0, PB - 14, 10.5, MUTED))

    # ── panel C · headline figures ─────────────────────────────────────
    figs = [(str(repos["count"]), "REPOSITORIES"),
            (str(s["total"]),     "CONTRIBUTIONS · 12M"),
            (str(s["active"]),    "ACTIVE DAYS"),
            (str(s["longest"]),   "LONGEST STREAK")]
    for i, (num, label) in enumerate(figs):
        y = PT + 38 + i * 46
        b.append(pin(num, C + 62, y + 10, 30, AMBER, 700, anchor="end"))
        b.append(cap(label, C + 78, y + 4, MUTED))

    # ── stats row ──────────────────────────────────────────────────────
    # No contribution heatmap here on purpose: GitHub already renders one
    # directly above the README, and two identical calendars on one page reads
    # as a mistake. This section carries only what GitHub does not show.
    b.append(f'<line x1="{M}" y1="{STAT_RULE}" x2="{W-M}" y2="{STAT_RULE}" stroke="{RULE}"/>')
    peak_d = dt.date.fromisoformat(s["busiest"]["d"])
    stats = [("CURRENT STREAK", f"{s['current']} day" + ("s" if s["current"] != 1 else "")),
             ("LAST COMMIT",    ago(s["last_active"], today)),
             ("BUSIEST DAY",    peak_d.strftime("%d %b %Y").lower()),
             ("PEAK VOLUME",    f"{s['busiest']['c']} commits")]
    colw = (W - 2 * M) / len(stats)
    for i, (lab, val) in enumerate(stats):
        x = M + i * colw
        b.append(cap(lab, x, STAT_LABEL, MUTED))
        b.append(pin(val, x, STAT_VALUE, 17, BONE))
        if len(lab) * CAP_ADV > colw - 12 or len(val) * 17 * 0.6 > colw - 12:
            warn.append(f"stats column '{lab}' overflows its {round(colw)}px slot")

    # The section ends at the calendar legend. The regenerated-at stamp and the
    # source credit used to live here; both were removed by request. The stamp
    # is still written into the SVG title/aria-label for provenance.
    return "\n".join(b), warn

# ── splice ────────────────────────────────────────────────────────────────
START, END = "<!--ACTIVITY:START-->", "<!--ACTIVITY:END-->"
SLUGS = {"WHOAMI": "whoami", "PROJECTS": "projects", "STACK": "stack",
         "ACTIVITY": "activity", "CONTACT": "contact"}

def label_of(block):
    m = re.search(r'class="cap"[^>]*>([A-Z]+)</text>', block)
    return m.group(1) if m else None

def renumber(block, idx):
    """Force a block's index numeral and path slug to match document order."""
    block = re.sub(r'(<text[^>]*font-size="46"[^>]*>)0x00\d(</text>)',
                   lambda m: m.group(1) + idx + m.group(2), block)
    block = re.sub(r'~/0x00\d-(\w+)', lambda m: f'~/{idx}-{m.group(1)}', block)
    block = re.sub(r'>FIG\. 00\d<', f'>FIG. {idx[-3:]}<', block)
    return block

def splice(svg_text, inner):
    tops = [m for m in re.finditer(r'<g transform="translate\(0,\s*(\d+)\)">', svg_text)
            if svg_text.count("<g", 0, m.start()) - svg_text.count("</g>", 0, m.start()) == 0]
    if not tops:
        raise RuntimeError("no top-level section groups found")

    def gend(m):
        d, j = 1, m.end()
        while d:
            o, c = svg_text.find("<g", j), svg_text.find("</g>", j)
            if o != -1 and o < c:
                d, j = d + 1, o + 2
            else:
                d, j = d - 1, c + 4
        return j

    vb = re.search(r'viewBox="0 0 \d+ (\d+)"', svg_text)
    canvas = int(vb.group(1)) if vb else None
    blocks, heights = [], []
    for i, m in enumerate(tops):
        blocks.append(svg_text[m.end():gend(m) - len("</g>")])
        nxt = int(tops[i + 1].group(1)) if i + 1 < len(tops) else canvas
        heights.append((nxt - int(m.group(1))) if nxt is not None else H)

    # Carry an explicit "is the activity block" flag. It used to be inferred
    # with `blk is inner`, but renumber() returns a new string, so the identity
    # was lost and the ACTIVITY markers silently never got written.
    keep = [(b, h, False) for b, h in zip(blocks, heights) if label_of(b) != "ACTIVITY"]

    # place activity immediately before contact, else at the end
    at = next((i for i, (b, _, _) in enumerate(keep) if label_of(b) == "CONTACT"), len(keep))
    keep.insert(at, (inner, H, True))

    # renumber every indexed section from its final position
    n = 0
    final = []
    for blk, h, is_act in keep:
        lab = label_of(blk)
        if lab in SLUGS:
            n += 1
            blk = renumber(blk, f"0x{n:03d}")
        final.append((blk, h, is_act))

    out, y = [], 0
    for blk, h, is_act in final:
        out.append((f'<g transform="translate(0, {y})">{blk}</g>', is_act))
        y += h
    body = "\n".join(f"{START}\n{g}\n{END}" if act else g for g, act in out)

    head, tail = svg_text[:tops[0].start()], svg_text[gend(tops[-1]):]
    for mk in (START, END):
        head, tail = head.replace(mk, ""), tail.replace(mk, "")
    head, tail = head.rstrip(), tail.lstrip()
    head = re.sub(r'viewBox="0 0 (\d+) \d+"', rf'viewBox="0 0 \1 {y}"', head)
    head = re.sub(r'(<svg[^>]*?)height="\d+"', rf'\1height="{y}"', head)
    head = re.sub(r'(<rect width="\d+" height=")\d+(")', rf'\g<1>{y}\g<2>', head)
    return head + "\n" + body + "\n" + tail

# ── main ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        days, dropped = fetch_calendar()
        repos = fetch_repos()
    except Exception as exc:
        print(f"::warning::fetch failed ({exc}); section left unchanged")
        return 0

    s = summarise(days)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%d %b %Y %H:%M UTC").upper()
    inner, warn = render(days, s, repos, stamp)

    style = ("text{font-family:ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,"
             "'DejaVu Sans Mono','Liberation Mono',monospace}"
             ".cap{font-size:11px;letter-spacing:.2em;font-weight:700}"
             ".path{font-size:11.5px}.meta{font-size:10.5px;letter-spacing:.2em}")
    with open(SECTION, "w") as f:
        f.write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" '
                f'height="{H}" role="img" aria-label="Activity telemetry — {repos["count"]} '
                f'repositories, {s["total"]} contributions in 12 months, {s["active"]} active '
                f'days, longest streak {s["longest"]} days. Regenerated {stamp}.">\n'
                f'<title>{USER} — activity telemetry, regenerated {stamp}</title>\n'
                f'<style>{style}</style>\n'
                f'<rect width="{W}" height="{H}" fill="{BG}"/>\n{inner}\n</svg>\n')

    print(f"repos {repos['count']} · contributions {s['total']} · active {s['active']}"
          f"/{s['span']} · streak {s['longest']} · langs {[l for l,_ in repos['langs']]}")
    print(f"future-dated cells discarded: {dropped} · window ends {s['to']}")

    over = list(warn)
    for tag in re.findall(r'<text [^>]*textLength="[^"]*"[^>]*>[^<]*</text>', inner):
        x   = float(re.search(r'\bx="([-\d.]+)"', tag).group(1))
        wid = float(re.search(r'textLength="([\d.]+)"', tag).group(1))
        am  = re.search(r'text-anchor="(\w+)"', tag)
        anc = am.group(1) if am else "start"
        txt = re.search(r'>([^<]*)</text>', tag).group(1)
        x1 = x - wid if anc == "end" else (x - wid / 2 if anc == "middle" else x)
        if x1 < M - 1 or x1 + wid > W - M + 1:
            over.append(f"outside margins [{round(x1)},{round(x1+wid)}]: {txt[:30]}")
    if over:
        for o in over:
            print(f"::warning::{o}")
    else:
        n_lbl = len(re.findall(r"<text ", inner))
        print(f"layout audit: {n_lbl} labels, no margin or column collisions")

    if args.dry_run or not os.path.exists(SVG):
        print(f"wrote {SECTION}")
        return 0

    original = open(SVG).read()
    updated = splice(original, inner)
    import xml.dom.minidom as minidom
    try:
        minidom.parseString(updated)
    except Exception as exc:
        print(f"::error::splice produced invalid XML ({exc}); {SVG} untouched")
        return 1

    # The rendered section carries no timestamp, so this comparison is exact:
    # portfolio.svg changes only when the underlying numbers change. That keeps
    # the cron from committing four times a day just to bump a clock.
    if updated == original:
        print(f"{SVG} unchanged — nothing to commit")
        return 0
    open(SVG, "w").write(updated)
    print(f"{SVG} updated")
    return 0

if __name__ == "__main__":
    sys.exit(main())
