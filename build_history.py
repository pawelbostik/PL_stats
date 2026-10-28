#!/usr/bin/env python3
"""Stáhne archiv starších sezon Premier League (od 2014/15) do site/hist/<rok>/.

Stahují se jen sezony, které ještě chybějí; hotová sezona se už nikdy nestahuje znovu.
Běh má časový limit (proměnná HIST_MINUTES, výchozí 40 minut), aby nezdržoval
pravidelnou aktualizaci – co se nestihne, dostáhne se příští běh.

Když je nastaveno COMMIT_PROGRESS=1 (v GitHub Actions), každá dokončená sezona se
hned uloží do repozitáře, aby se při přerušení nic neztratilo.
"""
import os
import shutil
import subprocess
import time

import build as b

MINUTES = float(os.environ.get("HIST_MINUTES", "40"))
COMMIT = os.environ.get("COMMIT_PROGRESS") == "1"


def commit(msg):
    if not COMMIT:
        return
    try:
        subprocess.run(["git", "add", "-A", "site", "cache"], check=True, cwd=b.ROOT)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=b.ROOT).returncode == 0:
            return
        subprocess.run(["git", "commit", "-q", "-m", msg], check=True, cwd=b.ROOT)
        branch = os.environ.get("GITHUB_REF_NAME", "main")
        subprocess.run(["git", "pull", "--rebase", "-q", "origin", branch], cwd=b.ROOT)
        subprocess.run(["git", "push", "-q", "origin", "HEAD:" + branch], check=True, cwd=b.ROOT)
        b.log("  uloženo do repozitáře: %s" % msg)
    except Exception as e:  # noqa: BLE001
        b.log("!! průběžné uložení selhalo: %s" % e)


def main():
    deadline = time.time() + MINUTES * 60
    todo = [y for y in range(int(b.SEASON) - 1, b.FIRST_SEASON - 1, -1)
            if not os.path.exists(os.path.join(b.SITE, "hist", str(y), "data.json"))]
    if not todo:
        b.log("Archiv je kompletní.")
        return
    b.log("Chybějící sezony: %s (limit %.0f min)" % (", ".join(b.label(y) for y in todo), MINUTES))
    for y in todo:
        if time.time() > deadline:
            break
        try:
            done = b.build(y, os.path.join(b.SITE, "hist", str(y)), current=False, deadline=deadline)
        except Exception as e:  # noqa: BLE001
            b.log("!! sezona %s selhala: %s" % (b.label(y), e))
            continue
        if done:
            # Hotová sezona je celá v site/hist/<rok>/, uložené zápasy už nejsou potřeba.
            shutil.rmtree(os.path.join(b.CACHE, "matches", str(y)), ignore_errors=True)
            b.write_seasons()
            commit("Archiv: sezona %s" % b.label(y))
        else:
            commit("Archiv: průběžně stažené zápasy sezony %s" % b.label(y))
    b.write_seasons()
    left = [y for y in todo if not os.path.exists(os.path.join(b.SITE, "hist", str(y), "data.json"))]
    b.log("Zbývá stáhnout: %s" % (", ".join(b.label(y) for y in left) if left else "nic, archiv je kompletní"))


if __name__ == "__main__":
    main()
