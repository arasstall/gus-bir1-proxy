"""Dobór raportu GUS wg typu podmiotu i normalizacja pól (m.in. dat działalności).

Klucze w odpowiedziach GUS bywają prefiksowane (np. ``praw_dataPowstania``,
``fiz_dataRozpoczeciaDzialalnosci``). Dopasowujemy je „rozmycie" — po znormalizowanej
nazwie (bez wielkości liter i znaków niealfanumerycznych, po podłańcuchu) — więc
kod jest odporny na dokładny prefiks danego raportu.
"""
from __future__ import annotations

import re
from typing import Any

# --- Dobór nazwy raportu na podstawie pola Typ / SilosID z wyszukiwania ---
#
# Nazwy raportów BIR 1.1 i 1.2 różnią się tylko prefiksem ("BIR11" vs "BIR12"),
# przyrostki są wspólne — więc nazwę składamy z prefiksu wg wersji + przyrostka.

# Przyrostek nazwy raportu wg typu podmiotu (Typ z wyszukiwania).
_SUFFIX_BY_TYP = {
    "P": "OsPrawna",
    "LP": "JednLokalnaOsPrawnej",
    "LF": "JednLokalnaOsFizycznej",
}
# Przyrostek dla osoby fizycznej (Typ == "F") wg SilosID.
_SUFFIX_BY_SILOS_F = {
    "1": "OsFizycznaDzialalnoscCeidg",
    "2": "OsFizycznaDzialalnoscRolnicza",
    "3": "OsFizycznaDzialalnoscPozostala",
}
_DEFAULT_SUFFIX = "OsFizycznaDaneOgolne"


def _report_prefix(bir_version: str | None) -> str:
    return "BIR12" if (bir_version or "").replace(".", "").startswith("bir12") else "BIR11"


def pick_report_name(typ: str | None, silos_id: Any, bir_version: str = "bir1.1") -> str:
    prefix = _report_prefix(bir_version)
    typ = (typ or "").upper()
    if typ in _SUFFIX_BY_TYP:
        suffix = _SUFFIX_BY_TYP[typ]
    elif typ == "F":
        suffix = _SUFFIX_BY_SILOS_F.get(str(silos_id), _DEFAULT_SUFFIX)
    else:
        suffix = _DEFAULT_SUFFIX
    return f"{prefix}{suffix}"


# --- Normalizacja kluczy ---

def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _normalized(row: dict[str, Any]) -> dict[str, Any]:
    return {_norm_key(k): v for k, v in row.items()}


def get_ci(row: dict[str, Any], needle: str) -> Any:
    """Pobiera wartość po znormalizowanej nazwie (dokładne dopasowanie, potem podłańcuch)."""
    norm = _normalized(row)
    n = _norm_key(needle)
    if n in norm:
        return norm[n]
    for k, v in norm.items():
        if n in k:
            return v
    return None


# Pola tożsamości z wyniku wyszukiwania (searchData).
IDENTITY_FIELDS: dict[str, str] = {
    "regon": "regon",
    "nip": "nip",
    "status_nip": "statusnip",
    "nazwa": "nazwa",
    "wojewodztwo": "wojewodztwo",
    "powiat": "powiat",
    "gmina": "gmina",
    "miejscowosc": "miejscowosc",
    "kod_pocztowy": "kodpocztowy",
    "ulica": "ulica",
    "nr_nieruchomosci": "nrnieruchomosci",
    "nr_lokalu": "nrlokalu",
    "typ": "typ",
    "silos_id": "silosid",
}

# Pola dat z pełnego raportu. Każde pole dopasowujemy po ZESTAWIE tokenów, które
# WSZYSTKIE muszą wystąpić w znormalizowanej nazwie pola. To eliminuje fałszywe
# trafienia — np. samo "zregon" łapało też "fiz_regon9" (numer REGON, nie datę).
DATE_FIELDS: dict[str, tuple[str, ...]] = {
    "data_powstania": ("powstania",),
    "data_rozpoczecia_dzialalnosci": ("rozpoczecia",),
    "data_wpisu_do_regon": ("wpisu", "doregon"),
    "data_zawieszenia_dzialalnosci": ("zawieszenia",),
    "data_wznowienia_dzialalnosci": ("wznowienia",),
    "data_zaistnienia_zmiany": ("zaistnienia",),
    "data_zakonczenia_dzialalnosci": ("zakonczenia", "dzialalnosci"),
    "data_skreslenia_z_regon": ("skreslenia", "zregon"),
}

# Stała kolejność kolumn (przydatna dla CSV/Excela).
FLAT_COLUMNS: list[str] = (
    list(IDENTITY_FIELDS.keys())
    + ["report_name", "status"]
    + list(DATE_FIELDS.keys())
)


def _empty_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def extract_dates(report_row: dict[str, Any]) -> dict[str, Any]:
    norm = _normalized(report_row)
    out: dict[str, Any] = {}
    for out_key, tokens in DATE_FIELDS.items():
        value = None
        for nk, v in norm.items():
            if all(t in nk for t in tokens):
                value = _empty_to_none(v)
                break
        out[out_key] = value
    return out


def compute_status(dates: dict[str, Any]) -> str:
    """Wylicza status działalności z dat GUS: aktywna / zawieszona / zamknieta.

    Daty są w formacie ISO ('YYYY-MM-DD'), więc porównania łańcuchowe działają
    poprawnie. Puste pola przychodzą już jako None (z extract_dates).
    """
    if dates.get("data_zakonczenia_dzialalnosci") or dates.get("data_skreslenia_z_regon"):
        return "zamknieta"

    zawieszenie = dates.get("data_zawieszenia_dzialalnosci")
    wznowienie = dates.get("data_wznowienia_dzialalnosci")
    if zawieszenie and (not wznowienie or wznowienie < zawieszenie):
        return "zawieszona"

    return "aktywna"


def flatten_entity(
    entity: dict[str, Any],
    report_name: str,
    report_row: dict[str, Any] | None,
) -> dict[str, Any]:
    """Buduje jeden płaski rekord: tożsamość + status + ujednolicone daty."""
    out: dict[str, Any] = {}
    for out_key, needle in IDENTITY_FIELDS.items():
        out[out_key] = _empty_to_none(get_ci(entity, needle))

    dates = extract_dates(report_row or {})
    out["report_name"] = report_name
    out["status"] = compute_status(dates)
    out.update(dates)
    return out
