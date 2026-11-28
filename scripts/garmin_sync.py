#!/usr/bin/env python3
"""Fetch this season's Garmin ski activities with a Personal API key and save them ENCRYPTED in garmin/.

Secrets (GitHub → Settings → Secrets and variables → Actions):
  GARMIN_API_KEY     Personal API key from connect.garmin.com/app/settings/personalApiToken
  GARMIN_PASSPHRASE  any passphrase; type the same one into Ski Days → Settings → Garmin

Files written (the site is public, so everything about your activities is encrypted):
  garmin/status.json   plain: ok / message / count / salt (no activity data)
  garmin/index.bin     encrypted list of imported activities
  garmin/<id>.bin      encrypted, gzipped original FIT/zip export for each activity
Encryption: AES-256-GCM, key = PBKDF2-SHA256(passphrase, salt, 150000). Blob = 12-byte IV + ciphertext.
"""
import datetime, gzip, hashlib, json, os, re, secrets, sys, urllib.request, urllib.error
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BASE = os.environ.get("GARMIN_BASE", "https://personal.connectapi.garmin.com")
OUT = sys.argv[1] if len(sys.argv) > 1 else "garmin"
ITER = 150000
UA = {"User-Agent": "SkiDays-sync/1.0 (personal use)", "Accept": "*/*"}

def status(**kw):
    path = os.path.join(OUT, "status.json")
    old = {}
    try: old = json.load(open(path))
    except Exception: pass
    new = {**{k: old[k] for k in ("salt",) if k in old}, **kw}
    if {k: v for k, v in old.items() if k != "updated"} != {k: v for k, v in new.items() if k != "updated"}:
        new["updated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        json.dump(new, open(path, "w"), indent=1)
    return new

def req(path, headers=None, method="GET", raw=False):
    r = urllib.request.Request(BASE + path, method=method, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(r, timeout=60) as resp:
        data = resp.read()
    return data if raw else json.loads(data.decode() or "null")

def main():
    os.makedirs(OUT, exist_ok=True)
    key, pw = os.environ.get("GARMIN_API_KEY", "").strip(), os.environ.get("GARMIN_PASSPHRASE", "")
    if not key or not pw:
        status(ok=False, message="Not set up yet: add the GARMIN_API_KEY and GARMIN_PASSPHRASE secrets in GitHub.", count=0); return
    try: st = json.load(open(os.path.join(OUT, "status.json")))
    except Exception: st = {}
    salt = bytes.fromhex(st["salt"]) if st.get("salt") else None
    index = None
    if salt:
        aes = AESGCM(hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITER, 32))
        try:
            b = open(os.path.join(OUT, "index.bin"), "rb").read()
            index = json.loads(aes.decrypt(b[:12], b[12:], None))
        except FileNotFoundError: index = {"acts": []}
        except Exception: index = None   # passphrase changed: start over
    if index is None:
        for f in os.listdir(OUT):
            if f.endswith(".bin"): os.remove(os.path.join(OUT, f))
        salt = secrets.token_bytes(16); index = {"acts": []}
        aes = AESGCM(hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITER, 32))
    enc = lambda data: (lambda iv: iv + aes.encrypt(iv, data, None))(secrets.token_bytes(12))

    # 1. key -> 24h token
    try:
        t = req("/personalapitoken-service/personal-api/personal-api-key/token", {"Authorization": "ApiKey " + key}, "POST", raw=True).decode().strip()
    except urllib.error.HTTPError as e:
        msg = "Garmin didn't accept the API key. Make a new key and update the GARMIN_API_KEY secret." if e.code in (401, 403) else f"Garmin refused the sign-in (HTTP {e.code})."
        status(ok=False, message=msg, count=len(index["acts"]), salt=salt.hex()); return
    except Exception as e:
        status(ok=False, message=f"Couldn't reach Garmin: {str(e)[:120]}", count=len(index["acts"]), salt=salt.hex()); return
    try:
        j = json.loads(t); t = j if isinstance(j, str) else j.get("accessToken") or j.get("access_token") or j.get("token") or t
    except Exception: pass
    auth = {"Authorization": "Bearer " + t}

    # 2. this season's activities (season starts Aug 1)
    today = datetime.date.today()
    y = today.year if today.month >= 8 else today.year - 1
    try:
        lst = req(f"/activitylist-service/activities/search/activities?start=0&limit=100&startDate={y}-08-01&endDate={today.isoformat()}", auth)
    except Exception as e:
        status(ok=False, message=f"Garmin wouldn't list activities: {str(e)[:120]}", count=len(index["acts"]), salt=salt.hex()); return
    if isinstance(lst, dict): lst = lst.get("activityList") or lst.get("activities") or []
    kind = lambda a: str((a.get("activityType") or {}).get("typeKey") if isinstance(a.get("activityType"), dict) else a.get("activityType") or a.get("activityTypeKey") or "")
    ski = [a for a in lst if re.search(r"ski|snowboard", kind(a), re.I) and not re.search(r"cross_country|skate_ski|classic_ski|xc", kind(a), re.I)]
    have = {str(a["id"]) for a in index["acts"]}
    new = [a for a in ski if str(a.get("activityId")) not in have][:40]

    # 3. download each new one, encrypt, save
    errors = 0
    for a in new:
        aid = str(a["activityId"])
        try: data = req(f"/download-service/files/activity/{aid}", auth, raw=True)
        except Exception: errors += 1; continue
        open(os.path.join(OUT, aid + ".bin"), "wb").write(enc(gzip.compress(data, 9, mtime=0)))
        index["acts"].append({"id": aid, "name": a.get("activityName"), "type": kind(a), "start": a.get("startTimeLocal"),
            "summary": {k: a.get(k) for k in ("distance", "elevationLoss", "maxSpeed", "duration", "startLatitude", "startLongitude", "startTimeGMT") if a.get(k) is not None}})
    if new and errors < len(new):
        open(os.path.join(OUT, "index.bin"), "wb").write(enc(json.dumps(index).encode()))
    n = len(index["acts"])
    msg = f"{n} Garmin ski day{'s' if n != 1 else ''} this season." + (f" {errors} couldn't be downloaded; will retry." if errors else "")
    status(ok=errors < max(1, len(new)), message=msg, count=n, salt=salt.hex())

if __name__ == "__main__":
    main()
