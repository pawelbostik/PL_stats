#!/usr/bin/env python3
"""Stáhne data Premier League z Understatu a uloží je do složky site/.

Spouští se automaticky přes GitHub Actions. Používá jen standardní knihovnu Pythonu.

Zdroj: Understat.com (tabulka, hráči, týmy, xG, xA a data jednotlivých střel).
Understat nemá oficiální rozhraní; stahujeme šetrně, s pauzami, a každý odehraný
zápas jen jednou (pak zůstává uložený ve složce cache/).

Výstup pro aktuální sezonu (site/), pro starší sezony (site/hist/<rok>/):
  data.json     – týmy, hráči a všechny zápasy sezony
  shots.json    – všechny střely sezony (pro mapy střel)
  apps.json     – výkony hráčů v jednotlivých zápasech (pro formu a detail zápasu)
Společné:
  seasons.json  – seznam dostupných sezon
  index.html    – stránka (z page.html)
"""
import gzip
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

LEAGUE = "EPL"
SEASON = os.environ.get("SEASON", "2026")  # Understat značí sezonu rokem začátku: 2026 = 2026/27
FIRST_SEASON = 2014
ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.environ.get("SITE_DIR", os.path.join(ROOT, "site"))
CACHE = os.path.join(ROOT, "cache")
BASE = "https://understat.com/"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36 (pl-statistiky; personal non-commercial stats page)")
PAUSE = 1.0  # sekundy mezi dotazy

os.makedirs(SITE, exist_ok=True)

RES = {"Goal": 0, "SavedShot": 1, "MissedShots": 2, "BlockedShot": 3, "ShotOnPost": 4, "OwnGoal": 5}
SIT = {"OpenPlay": 0, "FromCorner": 1, "SetPiece": 2, "DirectFreekick": 3, "Penalty": 4}
TYPE = {"RightFoot": 0, "LeftFoot": 1, "Head": 2, "OtherBodyPart": 3}


def log(*a):
    print(*a, flush=True)


def u(s):
    return html.unescape(s) if isinstance(s, str) else s


def num(x, cast=float):
    try:
        return cast(float(x))
    except (TypeError, ValueError):
        return cast(0)


def r3(x):
    return round(float(x), 3)


def label(season):
    y = int(season)
    return "%d/%02d" % (y, (y + 1) % 100)


def get(path, referer, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(BASE + path, headers={
                "User-Agent": UA, "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Encoding": "gzip", "X-Requested-With": "XMLHttpRequest", "Referer": BASE + referer})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            time.sleep(PAUSE)
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 401, 403, 404):
                break
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(3 * (i + 1))
    raise RuntimeError("%s: %s" % (path, last))


def wjson(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    log("  zapsáno %s (%.0f kB)" % (os.path.relpath(path, SITE), os.path.getsize(path) / 1024))


def prague_now():
    # Středoevropský čas včetně letního (poslední neděle března až poslední neděle října).
    now = datetime.now(timezone.utc)

    def last_sunday(y, m):
        d = datetime(y, m, 31, 1, tzinfo=timezone.utc)
        return d - timedelta(days=(d.weekday() + 1) % 7)
    summer = last_sunday(now.year, 3) <= now < last_sunday(now.year, 10)
    return now + timedelta(hours=2 if summer else 1)


# ---------------------------------------------------------------------------
def mcache(season):
    path = os.path.join(CACHE, "matches", str(season))
    os.makedirs(path, exist_ok=True)
    return path


def load_match(season, mid, refresh=False):
    path = os.path.join(mcache(season), "%s.json" % mid)
    if os.path.exists(path) and not refresh:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    d = get("getMatchData/%s" % mid, "match/%s" % mid)
    keep_s = ("id", "minute", "result", "X", "Y", "xG", "player", "h_a", "player_id", "situation", "shotType",
              "player_assisted", "lastAction")
    keep_r = ("player_id", "player", "position", "positionOrder", "time", "goals", "own_goals", "assists", "shots",
              "xG", "xA", "key_passes", "yellow_card", "red_card", "xGChain", "xGBuildup", "team_id")
    shots = d.get("shots") or {}
    rost = d.get("rosters") or {}
    m = {
        "shots": [{k: s.get(k) for k in keep_s} for side in ("h", "a") for s in (shots.get(side) or [])],
        "rosters": {side: [{k: r.get(k) for k in keep_r} for r in (rost.get(side) or {}).values()] for side in ("h", "a")},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, separators=(",", ":"))
    return m


def build(season, outdir, current=True, deadline=None):
    """Sestaví data jedné sezony do složky outdir.

    current=True: zápasy z posledních dvou dnů se stahují znovu (Understat je někdy opraví).
    deadline: čas (time.time()), po kterém se další zápasy už nestahují; vrací pak False
              a nic nezapíše, aby se příště pokračovalo.
    """
    season = str(season)
    log("Understat: liga %s, sezona %s" % (LEAGUE, label(season)))
    lg = get("getLeagueData/%s/%s" % (LEAGUE, season), "league/%s/%s" % (LEAGUE, season))
    teams_raw, players_raw, dates = lg["teams"], lg["players"], lg["dates"]
    title2id = {u(t["title"]): str(t["id"]) for t in teams_raw.values()}
    short = {}
    for d in dates:
        for side in ("h", "a"):
            short[str(d[side]["id"])] = d[side].get("short_title") or ""

    # --- zápasy sezony ---
    matches = []
    for d in sorted(dates, key=lambda d: (d["datetime"], int(d["id"]))):
        done = bool(d.get("isResult"))
        m = {"id": int(d["id"]), "d": d["datetime"][:16], "h": str(d["h"]["id"]), "a": str(d["a"]["id"]), "r": 1 if done else 0}
        if done:
            m.update(gh=num(d["goals"]["h"], int), ga=num(d["goals"]["a"], int), xh=r3(d["xG"]["h"]), xa=r3(d["xG"]["a"]))
        fc = d.get("forecast") or {}
        if fc:
            m["fc"] = [round(num(fc.get(k)), 3) for k in ("w", "d", "l")]
        matches.append(m)
    # kolo: každý tým hraje v kole jednou → pořadí zápasu týmu = kolo (odložené zápasy proto dostanou své kolo)
    seen = {}
    for m in matches:
        n = max(seen.get(m["h"], 0), seen.get(m["a"], 0)) + 1
        seen[m["h"]] = seen[m["a"]] = n
        m["k"] = n

    # --- detaily odehraných zápasů (cache) ---
    played = [m for m in matches if m["r"]]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    new = failed = 0
    shots, apps = [], []
    for m in played:
        recent = current and (now - datetime.strptime(m["d"], "%Y-%m-%d %H:%M")).total_seconds() < 2 * 86400
        cached = os.path.exists(os.path.join(mcache(season), "%s.json" % m["id"]))
        if not cached or recent:
            if deadline and time.time() > deadline:
                log("  časový limit: sezona %s nedokončena, pokračuje se příště" % label(season))
                return False
            new += 1
            if new % 50 == 0:
                log("  … staženo %d zápasů" % new)
        try:
            det = load_match(season, m["id"], refresh=recent)
        except Exception as e:  # noqa: BLE001
            log("!! zápas %s se nepodařilo stáhnout: %s" % (m["id"], e))
            failed += 1
            continue
        for s in det["shots"]:
            shots.append([m["id"], num(s["minute"], int), num(s["player_id"], int), 0 if s["h_a"] == "h" else 1,
                          round(num(s["X"]), 3), round(num(s["Y"]), 3), r3(s["xG"]), RES.get(s["result"], 2),
                          SIT.get(s["situation"], 0), TYPE.get(s["shotType"], 3), u(s.get("player_assisted") or ""),
                          s.get("lastAction") or ""])
        for side in ("h", "a"):
            tid = m[side]
            for r in det["rosters"][side]:
                pos = r.get("position") or ""
                apps.append([m["id"], num(r["player_id"], int), tid, pos, num(r["time"], int), num(r["goals"], int),
                             num(r["own_goals"], int), num(r["assists"], int), num(r["shots"], int), r3(r["xG"]),
                             r3(r["xA"]), num(r["key_passes"], int), num(r["yellow_card"], int), num(r["red_card"], int),
                             r3(r["xGChain"]), r3(r["xGBuildup"]), 0 if pos == "Sub" else 1])
    log("  zápasy: %d odehraných, %d staženo nově/obnoveno, %d selhalo" % (len(played), new, failed))
    if failed and not current:
        log("  sezona %s má chybějící zápasy, uloží se až příště" % label(season))
        return False

    # --- týmy ---
    teams = []
    for t in teams_raw.values():
        h = t.get("history") or []
        s = lambda k: sum(num(x.get(k)) for x in h)  # noqa: E731
        ppda_att = sum(num(x["ppda"]["att"]) for x in h)
        ppda_def = sum(num(x["ppda"]["def"]) for x in h)
        ppa_att = sum(num(x["ppda_allowed"]["att"]) for x in h)
        ppa_def = sum(num(x["ppda_allowed"]["def"]) for x in h)
        tid = str(t["id"])
        hm = [x for x in h if x.get("h_a") == "h"]
        teams.append({
            "id": tid, "n": u(t["title"]), "s": short.get(tid, ""),
            "z": len(h), "w": int(s("wins")), "d": int(s("draws")), "l": int(s("loses")),
            "gf": int(s("scored")), "ga": int(s("missed")), "pts": int(s("pts")),
            "xg": round(s("xG"), 2), "xga": round(s("xGA"), 2), "npxg": round(s("npxG"), 2), "npxga": round(s("npxGA"), 2),
            "xpts": round(s("xpts"), 2), "deep": int(s("deep")), "deepa": int(s("deep_allowed")),
            "ppda": round(ppda_att / ppda_def, 2) if ppda_def else None,
            "oppda": round(ppa_att / ppa_def, 2) if ppa_def else None,
            "home": [int(sum(num(x["pts"]) for x in hm)), len(hm)],
        })

    # --- hráči ---
    players = []
    for p in players_raw:
        tids = [title2id.get(x.strip()) for x in u(p["team_title"]).split(",")]
        players.append({
            "id": num(p["id"], int), "n": u(p["player_name"]), "t": [x for x in tids if x],
            "pos": p.get("position") or "", "gp": num(p["games"], int), "min": num(p["time"], int),
            "g": num(p["goals"], int), "a": num(p["assists"], int), "xg": round(num(p["xG"]), 2), "xa": round(num(p["xA"]), 2),
            "npg": num(p["npg"], int), "npxg": round(num(p["npxG"]), 2), "sh": num(p["shots"], int), "kp": num(p["key_passes"], int),
            "yc": num(p["yellow_cards"], int), "rc": num(p["red_cards"], int),
            "xgc": round(num(p["xGChain"]), 2), "xgb": round(num(p["xGBuildup"]), 2),
        })
    # aktuální tým hráče = tým z jeho posledního zápasu
    last_team = {}
    for a in apps:
        last_team[a[1]] = a[2]
    for p in players:
        lt = last_team.get(p["id"])
        if lt and lt in p["t"]:
            p["t"] = [lt] + [x for x in p["t"] if x != lt]

    data = {"season": season, "label": label(season), "league": "Premier League",
            "updated": prague_now().strftime("%Y-%m-%d %H:%M"), "archive": not current,
            "played": len(played), "total": len(matches), "teams": teams, "players": players, "matches": matches}
    # Nejdřív střely a výkony, data.json až nakonec: jeho existence znamená, že sezona je kompletní.
    wjson(os.path.join(outdir, "shots.json"), {"cols": ["m", "min", "pid", "side", "x", "y", "xg", "res", "sit", "type", "ast", "last"], "rows": shots})
    wjson(os.path.join(outdir, "apps.json"), {"cols": ["m", "pid", "tid", "pos", "min", "g", "og", "a", "sh", "xg", "xa", "kp", "yc", "rc", "xgc", "xgb", "start"], "rows": apps})
    wjson(os.path.join(outdir, "data.json"), data)
    return True


def write_seasons():
    hist = os.path.join(SITE, "hist")
    years = []
    if os.path.isdir(hist):
        years = sorted((int(y) for y in os.listdir(hist)
                        if y.isdigit() and os.path.exists(os.path.join(hist, y, "data.json"))), reverse=True)
    out = [{"s": SEASON, "l": label(SEASON), "cur": True}] + [{"s": str(y), "l": label(y)} for y in years if str(y) != SEASON]
    wjson(os.path.join(SITE, "seasons.json"), out)


SKELETON = ('<!doctype html>\n<html lang="cs">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
            '<style>[hidden]{display:none!important}</style>\n')


def build_page():
    src_path = os.path.join(ROOT, "page.html")
    if not os.path.exists(src_path):
        return
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    i = src.index("</style>") + len("</style>")
    head = src[:i].replace('<meta name="claude:viewport-fit-sides" content="cover">\n', "")
    page = SKELETON + head + "\n</head>\n<body>\n" + src[i:] + "\n</body>\n</html>\n"
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    log("  zapsáno index.html")


def main():
    ok = True
    try:
        build(SEASON, SITE, current=True)
    except Exception as e:  # noqa: BLE001
        log("!! Stažení dat selhalo, ponechávám předchozí data: %s" % e)
        ok = False
    write_seasons()
    build_page()
    if not ok and not os.path.exists(os.path.join(SITE, "data.json")):
        sys.exit(1)


if __name__ == "__main__":
    main()
