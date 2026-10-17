#!/usr/bin/env python3
"""Create a starter data/countries/<ISO3>.toml for every country and territory.

Usage:  python3 scripts/generate_country_stubs.py [--dry-run]

Sources:
  - ISO 3166-1 list: /usr/share/iso-codes/json/iso_3166-1.json
    (Debian/Ubuntu package iso-codes; no download needed)
  - Local-language names: Unicode CLDR (https://cldr.unicode.org), Unicode License.
    Rule: the place's name in each language CLDR marks as official (or de facto
    official) there, short form when CLDR has one, when it differs from the
    English name. Downloaded once into
    .cache/ (ignored by git).

Existing files are never overwritten, so this is safe to re-run.
Standard library only.
"""

import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "countries"
ISO_FILE = Path("/usr/share/iso-codes/json/iso_3166-1.json")

CLDR_VERSION = "48.0.0"
CLDR_BASE = "https://cdn.jsdelivr.net/npm"
CACHE_DIR = ROOT / ".cache" / f"cldr-{CLDR_VERSION}"
OFFICIAL_STATUSES = {"official", "de_facto_official"}

# Common English names where the ISO short name is inverted or formal (decision D9).
NAME_OVERRIDES = {
    "BRN": "Brunei",
    "COD": "Democratic Republic of the Congo",
    "COG": "Republic of the Congo",
    "FSM": "Micronesia",
    "PSE": "Palestine",
    "RUS": "Russia",
    "VAT": "Vatican City",
    "VGB": "British Virgin Islands",
    "VIR": "U.S. Virgin Islands",
}

# Local names where CLDR's form is not what the place calls itself.
LOCAL_NAME_OVERRIDES = {
    ("KP", "ko"): "조선",  # CLDR uses South Korean usage ("북한")
    ("CD", "fr"): "République démocratique du Congo",  # CLDR: informal "Congo-Kinshasa"
    ("CG", "fr"): "République du Congo",  # CLDR: informal "Congo-Brazzaville"
}

# Places not in ISO 3166-1 that get a page anyway (decision D9).
EXTRA_PLACES = [
    {"alpha_3": "XKX", "alpha_2": "XK", "name": "Kosovo"},  # World Bank code
]


def slugify(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.replace("'", "").replace("’", "").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def cldr_json(package, path):
    """Fetch a CLDR JSON file (cached). Returns None if it does not exist."""
    cached = CACHE_DIR / package / path
    if cached.exists():
        text = cached.read_text("utf-8")
        return json.loads(text) if text else None
    url = f"{CLDR_BASE}/{package}@{CLDR_VERSION}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        text = ""  # remember the miss
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(text, "utf-8")
    return json.loads(text) if text else None


def official_languages():
    """Map alpha-2 -> [language codes] that CLDR marks official there, most speakers first."""
    info = cldr_json("cldr-core", "supplemental/territoryInfo.json")["supplemental"]["territoryInfo"]
    result = {}
    for alpha2, data in info.items():
        langs = data.get("languagePopulation", {})
        official = [
            (lang, float(v.get("_populationPercent", 0)))
            for lang, v in langs.items()
            if v.get("_officialStatus") in OFFICIAL_STATUSES
        ]
        official.sort(key=lambda lp: -lp[1])
        result[alpha2] = [lang.replace("_", "-") for lang, _ in official]
    return result


_territory_names = {}


def territory_name(lang, alpha2):
    if lang not in _territory_names:
        data = cldr_json("cldr-localenames-full", f"main/{lang}/territories.json")
        _territory_names[lang] = (
            data["main"][lang]["localeDisplayNames"]["territories"] if data else None
        )
    names = _territory_names[lang]
    if not names:
        return None
    # Prefer CLDR's short form (e.g. "Palestine" over "Palestinian Territories").
    return names.get(f"{alpha2}-alt-short") or names.get(alpha2)


def same_name(a, b):
    """Compare names ignoring case and apostrophe style (’ vs ')."""
    return a.replace("’", "'").casefold() == b.replace("’", "'").casefold()


def toml_str(value):
    # JSON string escaping is valid TOML basic-string escaping.
    return json.dumps(value, ensure_ascii=False)


def render(place):
    lines = [
        f"# {place['name']}",
        f'iso3 = {toml_str(place["iso3"])}',
        f'iso2 = {toml_str(place["iso2"])}',
        f'name = {toml_str(place["name"])}',
        f'slug = {toml_str(place["slug"])}',
    ]
    if place["local_names"]:
        lines.append(f"# local_names: Unicode CLDR {CLDR_VERSION}, official languages")
        lines.append("local_names = [")
        for ln in place["local_names"]:
            lines.append(f"  {{ name = {toml_str(ln['name'])}, lang = {toml_str(ln['lang'])} }},")
        lines.append("]")
    return "\n".join(lines) + "\n"


def main():
    dry_run = "--dry-run" in sys.argv
    iso = json.loads(ISO_FILE.read_text("utf-8"))["3166-1"] + EXTRA_PLACES
    official = official_languages()
    missing_langs = set()

    places = []
    for c in iso:
        iso3, alpha2 = c["alpha_3"], c["alpha_2"]
        name = NAME_OVERRIDES.get(iso3) or c.get("common_name") or c["name"]
        local_names = []
        for lang in official.get(alpha2, []):
            if lang == "en":  # the English name is already shown
                continue
            local = LOCAL_NAME_OVERRIDES.get((alpha2, lang)) or territory_name(lang, alpha2)
            if local is None:
                missing_langs.add(lang)
            elif not any(same_name(local, n) for n in [name] + [ln["name"] for ln in local_names]):
                local_names.append({"name": local, "lang": lang})
        places.append({"iso3": iso3, "iso2": alpha2, "name": name,
                       "slug": slugify(name), "local_names": local_names})

    slugs = [p["slug"] for p in places]
    dupes = {s for s in slugs if slugs.count(s) > 1}
    if dupes:
        sys.exit(f"duplicate slugs: {sorted(dupes)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    created = skipped = 0
    for p in places:
        path = OUT_DIR / f"{p['iso3']}.toml"
        if path.exists():
            skipped += 1
            continue
        if not dry_run:
            path.write_text(render(p), "utf-8")
        created += 1

    with_local = sum(1 for p in places if p["local_names"])
    verb = "would create" if dry_run else "created"
    print(f"{len(places)} places: {verb} {created}, kept {skipped} existing; "
          f"{with_local} have local names")
    if missing_langs:
        print(f"no CLDR names available for official languages: {', '.join(sorted(missing_langs))}")


if __name__ == "__main__":
    main()
