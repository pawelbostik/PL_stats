# Statistiky Premier League

Přehledné statistiky hráčů a týmů anglické Premier League v češtině: tabulky, xG a xA, mapy střel, forma hráčů, detaily zápasů, archiv od sezony 2014/15 a Češi v Premier League.

Stránka: **https://pawelbostik.github.io/PL_stats/**

Aktualizuje se sama každý den ráno a kolem půlnoci po večerních zápasech (GitHub Actions → `build.py`) a je zveřejněná přes GitHub Pages.

## Jak to funguje

- `page.html` – vzhled a logika stránky
- `build.py` – stáhne data a uloží je do složky `site/` (tu GitHub Pages zveřejňuje)
- `cache/` – už stažené zápasy, aby se nemusely stahovat znovu
- `.github/workflows/update.yml` – plán automatické aktualizace a zveřejnění
- větev `nahled` – zkušební verze pro náhled, nic se z ní nezveřejňuje

Ruční spuštění: záložka **Actions** → **Aktualizace statistik** → **Run workflow**.

## Zdroje dat

- [Understat.com](https://understat.com) – tabulka, statistiky hráčů a týmů, xG, xA a data jednotlivých střel

Projekt je nekomerční.
