#!/usr/bin/env python3
"""Check every data/countries/*.toml file against the country data rules.

Usage:  python3 scripts/validate_countries.py
Exit code 1 if any error is found. Warnings (e.g. stale entries) do not fail.
Standard library only (Python 3.11+ for tomllib).

Country file format (all text values are quoted strings; dates are "YYYY-MM-DD"):

    iso3 = "LVA"                  # required; file must be named LVA.toml
    iso2 = "LV"                   # required
    name = "Latvia"               # required; common English name
    slug = "latvia"               # required; unique; used in the page URL
    aliases = ["..."]             # optional; extra search terms, not displayed
    local_names = [               # optional; name in local language(s)
      { name = "Latvija", lang = "lv" },
    ]
    page_last_reviewed = "2026-10-17"   # optional; set by a human only

    [emergency]                   # optional until researched
    general = "112"               # any of: general, police, ambulance, fire
    police = "110"
    notes = ""                    # optional plain-language note
    source = "https://..."        # where this was found
    status = "draft"              # draft | verified
    last_verified = "2026-10-17"  # required when verified; human only
    verified_by = "Jusefs Saade"  # required when verified; human only

    [crisis_directory]            # optional; link to a helpline directory
    url = "https://..."
    source / status / last_verified / verified_by   (as above)

    [[resources]]                 # zero or more
    category = "health-care"      # must be an id in data/categories.toml
    name = "..."                  # required
    url = "https://..."           # url and/or phone required
    phone = "+371 ..."
    description = "..."           # one or two plain-language sentences
    type = "government"           # government | ngo | international | other
    languages = ["lv", "en"]
    source / status / last_verified / verified_by   (as above)
"""

import datetime as dt
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COUNTRIES_DIR = ROOT / "data" / "countries"
CATEGORIES_FILE = ROOT / "data" / "categories.toml"
I18N_FILE = ROOT / "i18n" / "en.toml"

STALE_AFTER_DAYS = 365

RE_ISO3 = re.compile(r"^[A-Z]{3}$")
RE_ISO2 = re.compile(r"^[A-Z]{2}$")
RE_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RE_LANG = re.compile(r"^[a-z]{2,3}(-[A-Z][a-z]{3})?(-[A-Z]{2})?$")
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_SHORT_NUMBER = re.compile(r"^[0-9]{2,8}$")
RE_PHONE = re.compile(r"^\+?[0-9][0-9 ()\-]{1,24}$")

VERIFICATION_KEYS = {"source", "status", "last_verified", "verified_by"}
TOP_KEYS = {"iso3", "iso2", "name", "slug", "aliases", "local_names", "page_last_reviewed",
            "emergency", "crisis_directory", "resources"}
EMERGENCY_NUMBER_KEYS = {"general", "police", "ambulance", "fire"}
EMERGENCY_KEYS = EMERGENCY_NUMBER_KEYS | {"notes"} | VERIFICATION_KEYS
CRISIS_KEYS = {"url"} | VERIFICATION_KEYS
RESOURCE_KEYS = {"category", "name", "url", "phone", "description", "type",
                 "languages"} | VERIFICATION_KEYS
RESOURCE_TYPES = {"government", "ngo", "international", "other"}
STATUSES = {"draft", "verified"}


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def warn(self, where, msg):
        self.warnings.append(f"{where}: {msg}")


def check_date(r, where, key, value, today):
    if not isinstance(value, str) or not RE_DATE.match(value):
        r.error(where, f'{key} must be a quoted "YYYY-MM-DD" string')
        return None
    try:
        d = dt.date.fromisoformat(value)
    except ValueError:
        r.error(where, f"{key} is not a real date: {value}")
        return None
    if d > today:
        r.error(where, f"{key} is in the future: {value}")
    return d


def check_string(r, where, key, value, required=False):
    if value is None:
        if required:
            r.error(where, f"missing required {key}")
        return
    if not isinstance(value, str):
        r.error(where, f"{key} must be a quoted string")
    elif required and not value.strip():
        r.error(where, f"{key} must not be empty")


def check_url(r, where, key, value):
    if value is None or value == "":
        return
    if not isinstance(value, str):
        r.error(where, f"{key} must be a quoted string")
    elif value.startswith("http://"):
        r.warn(where, f"{key} uses http, prefer https: {value}")
    elif not value.startswith("https://"):
        r.error(where, f"{key} must start with https:// : {value}")


def check_unknown_keys(r, where, table, allowed):
    for key in table:
        if key not in allowed:
            r.error(where, f"unknown key '{key}' (typo?)")


def check_verification(r, where, table, today):
    """Shared rules for anything carrying source/status/last_verified/verified_by."""
    status = table.get("status")
    if status not in STATUSES:
        r.error(where, f"status must be one of {sorted(STATUSES)}, got {status!r}")
        return
    check_url(r, where, "source", table.get("source"))
    if not table.get("source"):
        r.warn(where, "no source recorded")
    last = table.get("last_verified")
    by = table.get("verified_by")
    if status == "verified":
        if last is None:
            r.error(where, "verified entries need last_verified")
        if not by:
            r.error(where, "verified entries need verified_by")
    if last is not None:
        d = check_date(r, where, "last_verified", last, today)
        if d and (today - d).days > STALE_AFTER_DAYS:
            r.warn(where, f"last verified {last}, over {STALE_AFTER_DAYS} days ago (may be out of date)")
    if by is not None:
        check_string(r, where, "verified_by", by)


def check_country(r, path, data, category_ids, today):
    where = path.name
    check_unknown_keys(r, where, data, TOP_KEYS)

    iso3 = data.get("iso3")
    if not isinstance(iso3, str) or not RE_ISO3.match(iso3):
        r.error(where, "iso3 must be three capital letters")
    elif path.stem != iso3:
        r.error(where, f"file name must match iso3 ({iso3}.toml)")
    if not isinstance(data.get("iso2"), str) or not RE_ISO2.match(data["iso2"]):
        r.error(where, "iso2 must be two capital letters")
    check_string(r, where, "name", data.get("name"), required=True)
    slug = data.get("slug")
    if not isinstance(slug, str) or not RE_SLUG.match(slug):
        r.error(where, "slug must be lowercase letters, digits and single hyphens")

    aliases = data.get("aliases", [])
    if not isinstance(aliases, list) or not all(isinstance(a, str) and a.strip() for a in aliases):
        r.error(where, "aliases must be a list of non-empty quoted strings")

    local_names = data.get("local_names", [])
    if not isinstance(local_names, list):
        r.error(where, "local_names must be a list")
        local_names = []
    for i, ln in enumerate(local_names):
        w = f"{where} local_names[{i}]"
        if not isinstance(ln, dict):
            r.error(w, "must be { name = \"...\", lang = \"..\" }")
            continue
        check_unknown_keys(r, w, ln, {"name", "lang"})
        check_string(r, w, "name", ln.get("name"), required=True)
        if not isinstance(ln.get("lang"), str) or not RE_LANG.match(ln["lang"]):
            r.error(w, "lang must be a language code like \"lv\" or \"sr-Latn\"")

    if "page_last_reviewed" in data:
        check_date(r, where, "page_last_reviewed", data["page_last_reviewed"], today)

    emergency = data.get("emergency")
    if emergency is not None:
        w = f"{where} [emergency]"
        if not isinstance(emergency, dict):
            r.error(w, "must be a table")
        else:
            check_unknown_keys(r, w, emergency, EMERGENCY_KEYS)
            numbers = [k for k in EMERGENCY_NUMBER_KEYS if emergency.get(k)]
            if not numbers:
                r.error(w, "needs at least one of general, police, ambulance, fire")
            for k in numbers:
                v = emergency[k]
                if not isinstance(v, str) or not RE_SHORT_NUMBER.match(v):
                    r.error(w, f"{k} must be a quoted short number like \"112\", got {v!r}")
            check_string(r, w, "notes", emergency.get("notes"))
            check_verification(r, w, emergency, today)

    crisis = data.get("crisis_directory")
    if crisis is not None:
        w = f"{where} [crisis_directory]"
        if not isinstance(crisis, dict):
            r.error(w, "must be a table")
        else:
            check_unknown_keys(r, w, crisis, CRISIS_KEYS)
            if not crisis.get("url"):
                r.error(w, "missing url")
            check_url(r, w, "url", crisis.get("url"))
            check_verification(r, w, crisis, today)

    resources = data.get("resources", [])
    if not isinstance(resources, list):
        r.error(where, "resources must be a list of [[resources]] tables")
        resources = []
    for i, res in enumerate(resources):
        w = f"{where} resources[{i}]"
        if not isinstance(res, dict):
            r.error(w, "must be a table")
            continue
        if res.get("name"):
            w += f" ({res['name']})"
        check_unknown_keys(r, w, res, RESOURCE_KEYS)
        if res.get("category") not in category_ids:
            r.error(w, f"category {res.get('category')!r} is not in data/categories.toml")
        check_string(r, w, "name", res.get("name"), required=True)
        check_url(r, w, "url", res.get("url"))
        phone = res.get("phone")
        if phone:
            if not isinstance(phone, str) or not (RE_PHONE.match(phone) or RE_SHORT_NUMBER.match(phone)):
                r.error(w, f"phone looks wrong: {phone!r}")
        if not res.get("url") and not phone:
            r.error(w, "needs a url or a phone number")
        check_string(r, w, "description", res.get("description"))
        if res.get("type") not in RESOURCE_TYPES:
            r.error(w, f"type must be one of {sorted(RESOURCE_TYPES)}")
        langs = res.get("languages", [])
        if not isinstance(langs, list) or not all(isinstance(x, str) and RE_LANG.match(x) for x in langs):
            r.error(w, "languages must be a list of language codes like [\"lv\", \"en\"]")
        check_verification(r, w, res, today)


def main():
    r = Report()
    today = dt.date.today()

    categories = tomllib.loads(CATEGORIES_FILE.read_text("utf-8")).get("categories", [])
    category_ids = [c.get("id") for c in categories]
    if len(set(category_ids)) != len(category_ids):
        r.error(CATEGORIES_FILE.name, "duplicate category ids")
    labels = tomllib.loads(I18N_FILE.read_text("utf-8"))
    for cid in category_ids:
        if f"cat_{cid}" not in labels:
            r.error(I18N_FILE.name, f"missing label cat_{cid}")

    files = sorted(COUNTRIES_DIR.glob("*.toml"))
    if not files:
        r.error(str(COUNTRIES_DIR), "no country files found")
    seen = {"iso3": {}, "iso2": {}, "slug": {}}
    for path in files:
        try:
            data = tomllib.loads(path.read_text("utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
            r.error(path.name, f"cannot parse: {e}")
            continue
        check_country(r, path, data, set(category_ids), today)
        for key, index in seen.items():
            value = data.get(key)
            if value in index:
                r.error(path.name, f"duplicate {key} {value!r} (also in {index[value]})")
            elif value:
                index[value] = path.name

    for w in r.warnings:
        print(f"warning: {w}")
    for e in r.errors:
        print(f"ERROR:   {e}")
    print(f"\n{len(files)} country files, {len(r.errors)} errors, {len(r.warnings)} warnings")
    return 1 if r.errors else 0


if __name__ == "__main__":
    sys.exit(main())
