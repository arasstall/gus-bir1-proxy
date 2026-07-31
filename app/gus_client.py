"""Cienki wrapper na bibliotekę RegonAPI z automatycznym (re)logowaniem.

API GUS BIR wymaga sesji: najpierw `Zaloguj` (zwraca sid ważny ~60 min),
potem kolejne wywołania z tym sid. Ta klasa trzyma jedną sesję i loguje się
ponownie, gdy sesja wygaśnie.

Używa wyłącznie metod potwierdzonych w dokumentacji RegonAPI:
authenticate(), searchData(), dataDownloadFullReport().
"""
from __future__ import annotations

import threading
from typing import Any

from RegonAPI import RegonAPI

from .config import Settings
from .reports import flatten_entity, get_ci, pick_report_name


class GusClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._api: RegonAPI | None = None

    def _build(self) -> RegonAPI:
        api = RegonAPI(
            bir_version=self._settings.bir_version,
            is_production=self._settings.production,
            timeout=self._settings.timeout,
            operation_timeout=self._settings.operation_timeout,
        )
        api.authenticate(key=self._settings.api_key)
        return api

    def _get_api(self) -> RegonAPI:
        with self._lock:
            if self._api is None:
                self._api = self._build()
            return self._api

    def _reset(self) -> None:
        with self._lock:
            self._api = None

    def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Wywołuje metodę RegonAPI; przy błędzie (np. wygasła sesja) loguje się
        ponownie i ponawia raz."""
        try:
            api = self._get_api()
            return getattr(api, method_name)(*args, **kwargs)
        except Exception:  # noqa: BLE001 - ponów raz po ponownym zalogowaniu
            self._reset()
            api = self._get_api()
            return getattr(api, method_name)(*args, **kwargs)

    # --- Publiczne operacje ---

    def search(
        self,
        *,
        nip: str | None = None,
        regon: str | None = None,
        krs: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._call("searchData", nip=nip, regon=regon, krs=krs) or []

    def full_report(self, *, regon: str, report_name: str) -> list[dict[str, Any]]:
        # Wywołanie pozycyjne — druga nazwa parametru bywa różna w wersjach biblioteki.
        return self._call("dataDownloadFullReport", regon, report_name) or []

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
            report = self.full_report(regon=str(entity_regon), report_name=report_name)
            if report:
                report_row = report[0]

        flat = flatten_entity(entity, report_name, report_row)
        if include_raw:
            flat["_raw_search"] = entity
            flat["_raw_report"] = report_row
        return flat

    def ensure_session(self) -> dict[str, Any]:
        """Wymusza (lub odświeża) zalogowanie i zwraca informacje konfiguracyjne.
        Służy jako lekki 'readiness' check bez wywoływania danych GUS."""
        self._get_api()
        return {
            "authenticated": True,
            "bir_version": self._settings.bir_version,
            "production": self._settings.production,
        }
