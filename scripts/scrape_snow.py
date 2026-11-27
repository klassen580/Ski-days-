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

# ---------- Resorts' own reports (centimetres, the numbers the hill posts) ----------
MONTHS_LONG = {m: i for i, m in enumerate(["january","february","march","april","may","june","july","august","september","october","november","december"], 1)}
def find_date(t, now):
    m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", t)
    if m:
        try: return datetime(int(m.group(3)), MONTHS_LONG[m.group(1).lower()], int(m.group(2))).date().isoformat()
        except ValueError: pass
    return None
def cm_after(label, t):
    m = re.search(label + r"\s*:?\s*(\d+(?:\.\d+)?)\s*cm", t, re.I)
    return round(float(m.group(1))) if m else None

def lake_louise(now):
    """reports.skilouise.com: 'Back Bowls' (upper) and 'Mid Mountain' blocks in cm."""
    for url in ["https://reports.skilouise.com/", "https://www.skilouise.com/snow-conditions/"]:
        try: t = text_of(fetch(url))
        except Exception: continue
        up_i = t.find("Back Bowls"); mid_i = t.find("Mid Mountain")
        if up_i < 0 or mid_i < 0: continue
        up, mid = (t[up_i:mid_i], t[mid_i:mid_i + 600]) if up_i < mid_i else (t[up_i:up_i + 600], t[mid_i:up_i])
        out = {"source_name": "Lake Louise snow report", "url": url,
               "overnight_cm": cm_after(r"Overnight", up), "new24_cm": cm_after(r"Last 24 Hours", up), "new48_cm": cm_after(r"Last 48 Hours", up),
               "new7_cm": cm_after(r"Last 7 Days", up), "base_cm": cm_after(r"Snow Depth", up), "season_cm": cm_after(r"Year to Date", up),
               "mid_overnight_cm": cm_after(r"Overnight", mid), "mid_new24_cm": cm_after(r"Last 24 Hours", mid), "mid_new7_cm": cm_after(r"Last 7 Days", mid),
               "mid_cm": cm_after(r"Snow Depth", mid), "mid_season_cm": cm_after(r"Year to Date", mid),
               "upper_label": "Back Bowls", "updated": find_date(t, now)}
        m = re.search(r"(\d+)\s+Lifts?,", t)
        if m: out["lifts_open"] = int(m.group(1))
        if out["new24_cm"] is not None or out["base_cm"] is not None:
            return {k: v for k, v in out.items() if v is not None}
    return None

def sunshine(now):
    """skibanff.com current conditions: Upper Mountain (7 day, base, cumulative) and Mid Mountain (24h, 7 days, settled base)."""
    url = "https://www.skibanff.com/the-mountain/mountain-report/current-conditions"
    try: t = text_of(fetch(url))
    except Exception: return None
    up_i = t.find("Upper Mountain Snow Report"); mid_i = t.find("Mid Mountain Snow Report")
    if up_i < 0 and mid_i < 0: return None
    up = t[up_i:up_i + 400] if up_i >= 0 else ""; mid = t[mid_i:mid_i + 500] if mid_i >= 0 else ""
    out = {"source_name": "Sunshine Village mountain report", "url": url,
           "new24_cm": cm_after(r"24 Hours", mid) if cm_after(r"24 Hours", mid) is not None else cm_after(r"24 Hours", up),
           "overnight_cm": cm_after(r"Overnight", mid), "new48_cm": cm_after(r"48 Hours", mid),
           "new7_cm": cm_after(r"7 Days?", up) if cm_after(r"7 Days?", up) is not None else cm_after(r"7 Days?", mid),
           "base_cm": cm_after(r"Base", up), "season_cm": cm_after(r"Cumulative", up) or cm_after(r"Year", t),
           "mid_new7_cm": cm_after(r"7 Days?", mid), "mid_cm": cm_after(r"Settled Base", t),
           "upper_label": "Upper mountain", "updated": find_date(t, now)}
    if out["new24_cm"] is None and out["base_cm"] is None: return None
    return {k: v for k, v in out.items() if v is not None}

RESORT_READERS = {"louise": lake_louise, "sunshine": sunshine}

def main(path):
    now = datetime.now(timezone(timedelta(hours=-7)))   # Mountain Standard Time
    try:
        old = json.load(open(path))
    except Exception:
        old = {}
    hills, errors = {}, {}
    for hid, paths in HILLS.items():
        if hid in RESORT_READERS:
            try: own = RESORT_READERS[hid](now)
            except Exception as e: own = None; errors[hid + "_resort"] = str(e)[:200]
            if own:
                own.setdefault("updated", now.date().isoformat())
                # fill gaps (lifts, closed flag, summit) from OnTheSnow below, but keep the resort's own numbers
                hills[hid] = own
            else:
                errors[hid + "_resort"] = errors.get(hid + "_resort", "resort page not readable; using OnTheSnow")
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
                if hid in hills:   # resort's own report wins; borrow only what it lacks
                    for k in ("lifts_open", "lifts_total", "runs_open", "runs_total", "closed", "summit_cm", "comment"):
                        if k in data and k not in hills[hid]: hills[hid][k] = data[k]
                else:
                    data["source_name"] = "OnTheSnow"
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
