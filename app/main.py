"""Serwer pośredniczący (REST -> SOAP) dla API GUS BIR1 (wyszukiwarka REGON)."""
from __future__ import annotations

import csv
import io
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response

from . import reports
from .config import Settings, get_settings
from .gus_client import GusClient
from .models import ReportResponse, SearchResponse

_INDEX_HTML = (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")

# Znacznik wersji — pozwala potwierdzić, że kontener działa na aktualnym kodzie.
APP_VERSION = "1.1.1-status"

# Jeden współdzielony klient (trzyma sesję GUS).
_client: GusClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = GusClient(get_settings())
    yield
    _client = None


app = FastAPI(
    title="GUS BIR1 Proxy",
    description="Proxy REST/JSON dla SOAP-owego API GUS BIR1 (wyszukiwarka REGON).",
    version=APP_VERSION,
    lifespan=lifespan,
)


def get_client() -> GusClient:
    if _client is None:  # pragma: no cover - inicjalizowane w lifespan
        raise HTTPException(status_code=503, detail="Klient GUS niezainicjalizowany.")
    return _client


def require_api_key(
    settings: Settings = Depends(get_settings),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Opcjonalna ochrona proxy nagłówkiem X-API-Key (gdy GUS_PROXY_API_KEY ustawione)."""
    if settings.proxy_api_key and x_api_key != settings.proxy_api_key:
        raise HTTPException(status_code=401, detail="Nieprawidłowy lub brakujący X-API-Key.")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index():
    """Prosty interfejs graficzny (wyszukiwarka + tabela + link do CSV)."""
    return HTMLResponse(_INDEX_HTML)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "version": APP_VERSION}


@app.get("/status", tags=["meta"], dependencies=[Depends(require_api_key)])
def status(client: GusClient = Depends(get_client)):
    """Sprawdza, czy proxy potrafi zalogować się do GUS (readiness)."""
    try:
        return client.ensure_session()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Błąd logowania do GUS: {exc}") from exc


@app.get(
    "/search/nip/{nip}",
    response_model=SearchResponse,
    tags=["search"],
    dependencies=[Depends(require_api_key)],
)
def search_by_nip(nip: str, client: GusClient = Depends(get_client)):
    return _do_search(client, nip=nip)


@app.get(
    "/search/regon/{regon}",
    response_model=SearchResponse,
    tags=["search"],
    dependencies=[Depends(require_api_key)],
)
def search_by_regon(regon: str, client: GusClient = Depends(get_client)):
    return _do_search(client, regon=regon)


@app.get(
    "/search/krs/{krs}",
    response_model=SearchResponse,
    tags=["search"],
    dependencies=[Depends(require_api_key)],
)
def search_by_krs(krs: str, client: GusClient = Depends(get_client)):
    return _do_search(client, krs=krs)


@app.get(
    "/report/{regon}",
    response_model=ReportResponse,
    tags=["report"],
    dependencies=[Depends(require_api_key)],
)
def full_report(
    regon: str,
    report_name: str = Query(
        ...,
        description="Nazwa raportu GUS, np. BIR11OsFizycznaDaneOgolne albo BIR11OsPrawna.",
    ),
    client: GusClient = Depends(get_client),
):
    try:
        results = client.full_report(regon=regon, report_name=report_name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Błąd GUS: {exc}") from exc
    return ReportResponse(regon=regon, report_name=report_name, results=results)


def _do_search(client: GusClient, **kwargs) -> SearchResponse:
    try:
        results = client.search(**kwargs)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Błąd GUS: {exc}") from exc
    if not results:
        raise HTTPException(status_code=404, detail="Nie znaleziono podmiotu.")
    return SearchResponse(count=len(results), results=results)


# --- Ujednolicone dane podmiotu (tożsamość + daty działalności) ---

def _csv_response(rows: list[dict], sep: str = ";") -> Response:
    """Buduje CSV z BOM (poprawne polskie znaki i separator w Excelu)."""
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=reports.FLAT_COLUMNS, delimiter=sep, extrasaction="ignore"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {k: ("" if row.get(k) is None else row.get(k)) for k in reports.FLAT_COLUMNS}
        )
    content = "﻿" + buf.getvalue()  # BOM: poprawne polskie znaki w Excelu
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="gus.csv"'},
    )


def _entity_response(client: GusClient, ident: dict, raw: bool, fmt: str, sep: str):
    try:
        data = client.entity_details(**ident, include_raw=raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Błąd GUS: {exc}") from exc
    if data is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono podmiotu.")
    if fmt.lower() == "csv":
        return _csv_response([data], sep=sep)
    return data


@app.get("/entity/nip/{nip}", tags=["entity"], dependencies=[Depends(require_api_key)])
def entity_by_nip(
    nip: str,
    raw: bool = Query(False, description="Dołącz surowe dane GUS."),
    format: str = Query("json", pattern="^(json|csv)$"),
    sep: str = Query(";", description="Separator kolumn dla CSV."),
    client: GusClient = Depends(get_client),
):
    return _entity_response(client, {"nip": nip}, raw, format, sep)


@app.get("/entity/regon/{regon}", tags=["entity"], dependencies=[Depends(require_api_key)])
def entity_by_regon(
    regon: str,
    raw: bool = Query(False),
    format: str = Query("json", pattern="^(json|csv)$"),
    sep: str = Query(";"),
    client: GusClient = Depends(get_client),
):
    return _entity_response(client, {"regon": regon}, raw, format, sep)


@app.get("/entity/krs/{krs}", tags=["entity"], dependencies=[Depends(require_api_key)])
def entity_by_krs(
    krs: str,
    raw: bool = Query(False),
    format: str = Query("json", pattern="^(json|csv)$"),
    sep: str = Query(";"),
    client: GusClient = Depends(get_client),
):
    return _entity_response(client, {"krs": krs}, raw, format, sep)


@app.get("/entities", tags=["entity"], dependencies=[Depends(require_api_key)])
def entities(
    nip: list[str] | None = Query(None, description="Powtarzalny parametr nip."),
    regon: list[str] | None = Query(None, description="Powtarzalny parametr regon."),
    krs: list[str] | None = Query(None, description="Powtarzalny parametr krs."),
    format: str = Query("json", pattern="^(json|csv)$"),
    sep: str = Query(";"),
    client: GusClient = Depends(get_client),
):
    """Wsadowe pobranie wielu podmiotów naraz — wygodne do zaciągnięcia do Excela."""
    idents = (
        [("nip", v) for v in (nip or [])]
        + [("regon", v) for v in (regon or [])]
        + [("krs", v) for v in (krs or [])]
    )
    if not idents:
        raise HTTPException(status_code=400, detail="Podaj co najmniej jeden: nip, regon lub krs.")

    rows: list[dict] = []
    errors: list[dict] = []
    for kind, value in idents:
        try:
            data = client.entity_details(**{kind: value})
        except Exception as exc:  # noqa: BLE001
            errors.append({"query": {kind: value}, "error": str(exc)})
            continue
        if data is None:
            errors.append({"query": {kind: value}, "error": "nie znaleziono"})
        else:
            rows.append(data)

    if format.lower() == "csv":
        return _csv_response(rows, sep=sep)
    return {"count": len(rows), "results": rows, "errors": errors}


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
