#!/usr/bin/env python3
"""Sonda: ověří, že se data z Understatu dají stáhnout z GitHub Actions.

Nic nezveřejňuje – jen uloží výsledky do site/sonda.json a vzorky surových
dat do cache/sonda_*.json ve větvi „nahled“. Používá jen standardní knihovnu.
"""
import gzip
import http.cookiejar
import json
import os
import time
import traceback
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "site")
CACHE = os.path.join(ROOT, "cache")
os.makedirs(SITE, exist_ok=True)
os.makedirs(CACHE, exist_ok=True)

BASE = "https://understat.com/"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36 (pl-statistiky; personal non-commercial stats page)")
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
report = {"cas": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "testy": []}


def fetch(path, ajax=True, referer=None):
    headers = {"User-Agent": UA, "Accept-Encoding": "gzip",
               "Accept": "application/json, text/javascript, */*; q=0.01" if ajax else "text/html,*/*"}
    if ajax:
        headers["X-Requested-With"] = "XMLHttpRequest"
    if referer:
        headers["Referer"] = BASE + referer
    req = urllib.request.Request(BASE + path, headers=headers)
    with opener.open(req, timeout=60) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return r.status, r.headers.get("Content-Type", ""), raw


def test(name, path, ajax=True, referer=None, save=None):
    t0 = time.time()
    item = {"test": name, "adresa": BASE + path}
    data = None
    try:
        status, ctype, raw = fetch(path, ajax, referer)
        item.update(status=status, typ=ctype, velikost_kB=round(len(raw) / 1024, 1))
        if ajax:
            data = json.loads(raw.decode("utf-8"))
            item["ok"] = True
            if isinstance(data, dict):
                item["klice"] = {k: (type(v).__name__, len(v) if hasattr(v, "__len__") else None)
                                 for k, v in data.items()}
            if save:
                with open(os.path.join(CACHE, save), "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
        else:
            text = raw.decode("utf-8", "replace")
            item["ok"] = status == 200
            item["obsahuje_data_v_html"] = any(q in text for q in ("teamsData", "datesData", "playersData"))
            item["zacatek"] = text[:300]
    except Exception as e:  # noqa: BLE001
        item["ok"] = False
        item["chyba"] = repr(e)
        body = getattr(e, "read", None)
        if body:
            try:
                item["odpoved"] = body()[:500].decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
        item["traceback"] = traceback.format_exc()[-800:]
    item["sekund"] = round(time.time() - t0, 2)
    report["testy"].append(item)
    print(json.dumps({k: v for k, v in item.items() if k != "traceback"}, ensure_ascii=False), flush=True)
    time.sleep(2)
    return data


# 1) HTML stránka ligy (získá i cookies, kdyby je rozhraní vyžadovalo)
test("html_liga", "league/EPL/2026", ajax=False)
# 2) Data aktuální sezony 2026/27
league = test("liga_2026", "getLeagueData/EPL/2026", referer="league/EPL/2026", save="sonda_liga_2026.json")
# 3) Jedna stará sezona 2014/15
test("liga_2014", "getLeagueData/EPL/2014", referer="league/EPL/2014", save="sonda_liga_2014.json")

match_id = player_id = team = None
if isinstance(league, dict):
    dates = league.get("dates") or []
    done = [d for d in dates if d.get("isResult")]
    report["zapasy"] = {"celkem": len(dates), "odehrano": len(done)}
    if done:
        last = done[-1]
        match_id = str(last.get("id"))
        report["ukazka_zapasu"] = last
    players = league.get("players") or []
    if players:
        top = sorted(players, key=lambda p: float(p.get("xG", 0) or 0), reverse=True)[0]
        player_id = str(top.get("id"))
        report["ukazka_hrace"] = top
    teams = league.get("teams") or {}
    if teams:
        first = next(iter(teams.values()))
        team = first.get("title")
        report["ukazka_tymu"] = {k: first[k] for k in first if k != "history"}
        report["ukazka_tymu"]["history_prvni"] = (first.get("history") or [None])[0]

# 4) Jeden zápas se střelami a sestavami
if match_id:
    m = test("zapas", "getMatchData/" + match_id, referer="match/" + match_id, save="sonda_zapas.json")
    if isinstance(m, dict):
        shots = m.get("shots") or {}
        h = (shots.get("h") or [None])[0] if isinstance(shots, dict) else None
        report["ukazka_strely"] = h
        rost = m.get("rosters") or {}
        if isinstance(rost, dict) and rost.get("h"):
            report["ukazka_sestavy"] = next(iter(rost["h"].values()))
# 5) Hráč (zápasy a střely za kariéru)
if player_id:
    p = test("hrac", "getPlayerData/" + player_id, referer="player/" + player_id, save="sonda_hrac.json")
    if isinstance(p, dict):
        report["ukazka_hrac_zapas"] = (p.get("matches") or [None])[0]
# 6) Tým
if team:
    slug = team.replace(" ", "_")
    test("tym", "getTeamData/%s/2026" % slug, referer="team/%s/2026" % slug)

report["vysledek"] = "VŠE OK" if all(t.get("ok") for t in report["testy"]) else "NĚKTERÉ TESTY SELHALY"
with open(os.path.join(SITE, "sonda.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)
print(report["vysledek"])
