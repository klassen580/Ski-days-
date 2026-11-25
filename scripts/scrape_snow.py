#!/usr/bin/env python3
"""Read official, resort-reported snow numbers for Ski Days and save them as snow-report.json.

Source: OnTheSnow ski report pages, which republish each resort's own daily report.
Runs hourly from .github/workflows/snow-reports.yml. Standard library only.
"""
import html, json, re, sys, time, urllib.request
from datetime import datetime, timezone, timedelta

# hill id in the app -> candidate OnTheSnow paths (first one that works wins)
HILLS = {
    "louise":       ["alberta/lake-louise"],
    "sunshine":     ["alberta/sunshine-village", "alberta/banff-sunshine"],
    "norquay":      ["alberta/ski-banff-norquay", "alberta/mt-norquay", "alberta/banff-norquay"],
    "nakiska":      ["alberta/nakiska-ski-area", "canada/nakiska-ski-area"],
    "marmot":       ["alberta/marmot-basin", "canada/marmot-basin"],
    "castle":       ["alberta/castle-mountain", "alberta/castle-mountain-resort"],
    "winsport":     ["alberta/canada-olympic-park", "alberta/winsport-canada-olympic-park"],
    "kickinghorse": ["british-columbia/kicking-horse", "british-columbia/kicking-horse-mountain-resort"],
    "revelstoke":   ["british-columbia/revelstoke-mountain", "british-columbia/revelstoke-mountain-resort"],
    "fernie":       ["british-columbia/fernie-alpine", "british-columbia/fernie-alpine-resort"],
    "panorama":     ["british-columbia/panorama-mountain-village", "british-columbia/panorama-mountain-resort", "british-columbia/panorama"],
    "kimberley":    ["british-columbia/kimberley-alpine-resort", "british-columbia/kimberley"],
    "whistler":     ["british-columbia/whistler-blackcomb"],
    "bigwhite":     ["british-columbia/big-white", "british-columbia/big-white-ski-resort"],
    "sunpeaks":     ["british-columbia/sun-peaks", "british-columbia/sun-peaks-resort"],
}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
MONTHS = {m: i for i, m in enumerate(["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}
NUM = r"(\d+(?:\.\d+)?)"
UNIT = r"\s*(\"|”|″|in\b|cm\b)"

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html", "Accept-Language": "en-CA,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")

def text_of(page):
    page = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    return re.sub(r"\s+", " ", html.unescape(page)).strip()

def to_cm(v, unit):
    v = float(v)
    return round(v if unit.startswith("cm") else v * 2.54)

def report_date(mon, day, now):
    d = datetime(now.year, MONTHS[mon], int(day))
    if d.date() > (now + timedelta(days=2)).date():   # e.g. "Dec 30" read in January
        d = d.replace(year=now.year - 1)
    return d.date().isoformat()

def parse(t, now):
    out = {}
    m = re.search(r"Snow Report Last Updated:?\s*([A-Z][a-z]{2})\w*\.?\s+(\d{1,2})", t)
    if m and m.group(1) in MONTHS: out["updated"] = report_date(m.group(1), m.group(2), now)
    m = re.search(r"is a " + NUM + UNIT + r" base depth", t)
    if m: out["base_cm"] = to_cm(m.group(1), m.group(2))
    m = re.search(r"Mid Mountain\s*" + NUM + UNIT, t)
    if m: out["mid_cm"] = to_cm(m.group(1), m.group(2))
    m = re.search(r"Summit\s*(?:[\d,]+\s*(?:'|ft|m)\s*)?" + NUM + UNIT, t)
    if m: out["summit_cm"] = to_cm(m.group(1), m.group(2))
    m = re.search(r"(?:5|7)-day total\s*" + NUM + UNIT + r"\s*((?:" + NUM + UNIT + r"\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Today)\s*)+)", t)
    if m:
        out["recent_total_cm"] = to_cm(m.group(1), m.group(2))
        days = [{"label": lab, "cm": to_cm(v, u)} for v, u, lab in re.findall(NUM + UNIT + r"\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun|Today)", m.group(3))]
        out["days"] = days
        if days:
            out["new24_cm"] = days[-1]["cm"]
            out["new48_cm"] = sum(d["cm"] for d in days[-2:])
            out["latest_label"] = days[-1]["label"]
    elif re.search(r"No recent snowfall reported", t):
        out["new24_cm"] = 0; out["new48_cm"] = 0
    m = re.search(r"Lifts Open\s*(\d+)\s*/\s*(\d+)", t) or re.search(r"with (\d+) of (\d+) lifts open", t)
    if m: out["lifts_open"], out["lifts_total"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"Runs Open\s*(\d+)\s*/\s*(\d+)", t)
    if m: out["runs_open"], out["runs_total"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"Snow Reporter Comments?:?\s*(.{10,240}?)(?:\s+(?:SkiGPT|Read more|Lifts Open|Resort Overview|Powder Alerts)|$)", t)
    if m: out["comment"] = m.group(1).strip()
    out["closed"] = bool(re.search(r"is closed for the season", t))
    return out

def main(path):
    now = datetime.now(timezone(timedelta(hours=-7)))   # Mountain Standard Time
    try:
        old = json.load(open(path))
    except Exception:
        old = {}
    hills, errors = {}, {}
    for hid, paths in HILLS.items():
        last = "not found"
        for p in paths:
            url = f"https://www.onthesnow.com/{p}/skireport"
            try:
                t = text_of(fetch(url))
            except Exception as e:
                last = f"{p}: {e}"; continue
            data = parse(t, now)
            if "updated" in data or "base_cm" in data:
                data["url"] = url
                hills[hid] = data
                break
            last = f"{p}: page loaded but no snow report found"
        else:
            errors[hid] = last
        time.sleep(1.5)   # be polite
    # keep a hill's last good report if this run failed for it
    for hid, prev in (old.get("hills") or {}).items():
        if hid not in hills and hid in HILLS:
            hills[hid] = prev
    data = {"source": "OnTheSnow (resort-reported)", "hills": hills, "errors": errors}
    if {k: old.get(k) for k in data} == data:
        print("No changes."); return
    data["generated"] = now.isoformat(timespec="minutes")
    with open(path, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    print(f"Wrote {len(hills)} hills, {len(errors)} errors: {errors}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "snow-report.json")
