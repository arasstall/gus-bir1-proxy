"""Cienki wrapper na bibliotekę RegonAPI z automatycznym (re)logowaniem.

API GUS BIR wymaga sesji: najpierw `Zaloguj` (zwraca sid ważny ~60 min),
potem kolejne wywołania z tym sid. Ta klasa trzyma jedną sesję i loguje się
ponownie, gdy sesja wygaśnie.

Dwie pułapki GUS, które trzeba tu obsłużyć:

1. Po wygaśnięciu sesji `searchData` **nie rzuca wyjątku** — zwraca `None`,
   dokładnie tak samo jak przy nieistniejącym podmiocie. Samo ponawianie po
   wyjątku więc nie wystarcza; pusty wynik dodatkowo weryfikujemy pytając GUS
   o `StatusSesji` i dopiero pustka na świeżej sesji znaczy "nie ma podmiotu".

2. Gdy podmiotu nie ma, GUS **nie zwraca pustki**, tylko rekord z `ErrorCode`
   ("Nie znaleziono podmiotu..."). Nieodfiltrowany udaje znaleziony podmiot bez
   żadnych dat, a taki wychodzi z `compute_status` jako "aktywna".

Używa wyłącznie metod potwierdzonych w dokumentacji RegonAPI:
authenticate(), searchData(), dataDownloadFullReport().
"""
from __future__ import annotations

import threading
import time
from typing import Any

from RegonAPI import RegonAPI
from RegonAPI.exceptions import ApiError

from .config import Settings
from .reports import flatten_entity, get_ci, pick_report_name

# GUS unieważnia sid po ok. 60 min — odświeżamy z zapasem, zanim zdąży wygasnąć.
SESSION_MAX_AGE_SECONDS = 30 * 60

# Wyjątki RegonAPI dziedziczą po BaseException, więc samo `except Exception`
# by ich nie złapało.
CALL_ERRORS = (Exception, ApiError)


def drop_error_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Odsiewa rekordy-błędy GUS (te z `ErrorCode`), żeby nie udawały danych."""
    return [row for row in (rows or []) if not get_ci(row, "errorcode")]


class GusClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._api: RegonAPI | None = None
        self._authenticated_at = 0.0

    def _build(self) -> RegonAPI:
        api = RegonAPI(
            bir_version=self._settings.bir_version,
            is_production=self._settings.production,
            timeout=self._settings.timeout,
            operation_timeout=self._settings.operation_timeout,
        )
        api.authenticate(key=self._settings.api_key)
        return api

    def _get_api(self, *, force_new: bool = False) -> RegonAPI:
        with self._lock:
            too_old = (
                time.monotonic() - self._authenticated_at >= SESSION_MAX_AGE_SECONDS
            )
            if force_new or self._api is None or too_old:
                self._api = self._build()
                self._authenticated_at = time.monotonic()
            return self._api

    def _session_alive(self) -> bool:
        """Pyta GUS wprost o stan sesji: "1" = żywa, "0" = wygasła."""
        api = self._api
        if api is None:
            return False
        try:
            value = api.service.GetValue(pNazwaParametru="StatusSesji")
        except CALL_ERRORS:
            return False
        return str(value).strip() == "1"

    def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Wywołuje metodę RegonAPI; przy błędzie (np. zerwane połączenie)
        loguje się ponownie i ponawia raz."""
        try:
            api = self._get_api()
            return getattr(api, method_name)(*args, **kwargs)
        except CALL_ERRORS:
            api = self._get_api(force_new=True)
            return getattr(api, method_name)(*args, **kwargs)

    def _call_checked(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Jak `_call`, ale pusty wynik traktuje jako podejrzany — GUS zwraca
        `None` zarówno gdy podmiotu nie ma, jak i gdy sesja wygasła. Dopytujemy
        o stan sesji i tylko gdy jest martwa, logujemy się ponownie i ponawiamy.
        Dzięki temu realne "nie znaleziono" nie kosztuje dodatkowego logowania."""
        result = self._call(method_name, *args, **kwargs)
        if not result and not self._session_alive():
            self._get_api(force_new=True)
            result = self._call(method_name, *args, **kwargs)
        return result

    # --- Publiczne operacje ---

    def search(
        self,
        *,
        nip: str | None = None,
        regon: str | None = None,
        krs: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._call_checked("searchData", nip=nip, regon=regon, krs=krs)
        return drop_error_rows(rows)

    def full_report(self, *, regon: str, report_name: str) -> list[dict[str, Any]]:
        # Wywołanie pozycyjne — druga nazwa parametru bywa różna w wersjach biblioteki.
        # Bez filtrowania: /report jest udokumentowany jako surowy raport, więc
        # komunikat błędu z GUS jest tam użyteczną informacją.
        return self._call_checked("dataDownloadFullReport", regon, report_name) or []

    def entity_details(
        self,
        *,
        nip: str | None = None,
        regon: str | None = None,
        krs: str | None = None,
        include_raw: bool = False,
    ) -> dict[str, Any] | None:
        """Wyszukuje podmiot, dobiera właściwy raport wg typu, pobiera go i zwraca
        ujednolicony, płaski rekord (tożsamość + daty działalności).

        Zwraca None, gdy nie znaleziono podmiotu.
        """
        results = self.search(nip=nip, regon=regon, krs=krs)
        if not results:
            return None

        entity = results[0]
        typ = get_ci(entity, "typ")
        silos_id = get_ci(entity, "silosid")
        entity_regon = get_ci(entity, "regon")

        report_name = pick_report_name(typ, silos_id, self._settings.bir_version)
        report_row: dict[str, Any] = {}
        if entity_regon:
            # Rekord-błąd nie może tu wejść: nie ma dat, więc podmiot wyszedłby
            # jako "aktywna" niezależnie od stanu faktycznego.
            report = drop_error_rows(
                self.full_report(regon=str(entity_regon), report_name=report_name)
            )
            if report:
                report_row = report[0]

        flat = flatten_entity(entity, report_name, report_row)
        if include_raw:
            flat["_raw_search"] = entity
            flat["_raw_report"] = report_row
        return flat

    def ensure_session(self) -> dict[str, Any]:
        """Sprawdza, czy sesja z GUS naprawdę żyje (a nie tylko czy obiekt klienta
        istnieje). Gdy wygasła — loguje się ponownie."""
        self._get_api()
        alive = self._session_alive()
        if not alive:
            self._get_api(force_new=True)
            alive = self._session_alive()
        return {
            "authenticated": alive,
            "bir_version": self._settings.bir_version,
            "production": self._settings.production,
            "session_age_seconds": int(time.monotonic() - self._authenticated_at),
        }
