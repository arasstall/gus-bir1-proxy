# 🇵🇱 GUS BIR1 Proxy

> Lekki serwer pośredniczący, który zamienia toporne, SOAP-owe **API GUS BIR1**
> (wyszukiwarka REGON) w wygodne **REST/JSON + CSV**. Odpytujesz firmę po
> NIP / REGON / KRS i dostajesz gotowe dane wraz z **datami** i **statusem
> działalności** — bez grzebania w SOAP, WS-Addressing i sesjach.

Ukrywa całą złożoność GUS: logowanie kluczem, zarządzanie sesją (`sid`),
WS-Addressing i dobór właściwego raportu wg typu podmiotu. Zbudowany na
**FastAPI** + [`RegonAPI`](https://pypi.org/project/RegonAPI/), gotowy pod
**Docker** i **Synology Container Manager**.

### Co potrafi
- 🔎 **Wyszukiwanie** po NIP / REGON / KRS (pojedynczo i wsadowo)
- 🏢 **Ujednolicone dane** podmiotu (nazwa, adres, typ) niezależnie od tego,
  czy to osoba fizyczna czy prawna
- 📅 **Daty działalności**: powstanie, rozpoczęcie, zawieszenie, wznowienie,
  zakończenie, skreślenie z REGON
- 🚦 **Status**: `aktywna` / `zawieszona` / `zamknieta` — idealne do CRM
- 📊 **Eksport CSV** do Excela / Power Query (odświeżalne połączenie)
- 🖥️ Proste **GUI** w przeglądarce + interaktywny Swagger (`/docs`)
- 🔐 Ochrona nagłówkiem **`X-API-Key`**, gotowy pod reverse proxy z HTTPS

## Szybki start (Docker)

```bash
cp .env.example .env
# (opcjonalnie edytuj .env — np. wpisz produkcyjny GUS_API_KEY)

docker compose up --build
```

Domyślnie startuje w środowisku **testowym** GUS z publicznym kluczem
`abcde12345abcde12345`. API dostępne pod `http://localhost:8000`,
dokumentacja Swagger: `http://localhost:8000/docs`.

## Konfiguracja (zmienne środowiskowe)

| Zmienna | Domyślnie | Opis |
|---|---|---|
| `GUS_API_KEY` | `abcde12345abcde12345` | Klucz użytkownika GUS. Produkcyjny klucz uzyskuje się w GUS. |
| `GUS_PRODUCTION` | `false` | `true` = środowisko produkcyjne, `false` = testowe. |
| `GUS_BIR_VERSION` | `bir1.1` | `bir1` albo `bir1.1` (obsługiwane przez RegonAPI). |
| `GUS_TIMEOUT` | `15` | Timeout połączenia (s). |
| `GUS_OPERATION_TIMEOUT` | `15` | Timeout operacji (s). |
| `GUS_PROXY_API_KEY` | (puste) | Jeśli ustawione, proxy wymaga nagłówka `X-API-Key`. |

> **Uwaga:** klucz testowy działa tylko na danych testowych GUS. Do danych
> produkcyjnych potrzebny jest własny klucz produkcyjny i `GUS_PRODUCTION=true`.

## Endpointy

| Metoda | Ścieżka | Opis |
|---|---|---|
| GET | `/` | **Interfejs graficzny** (wyszukiwarka + tabela + pobranie CSV). |
| GET | `/docs` | Swagger UI (interaktywne API). |
| GET | `/health` | Liveness. |
| GET | `/status` | Sprawdza logowanie do GUS. |
| GET | `/entity/nip/{nip}` | **Ujednolicone dane + daty** (auto-wykrywanie typu podmiotu). |
| GET | `/entity/regon/{regon}` | j.w. po REGON. |
| GET | `/entity/krs/{krs}` | j.w. po KRS. |
| GET | `/entities?nip=..&nip=..` | **Wsadowo** wiele podmiotów (do Excela). |
| GET | `/search/nip\|regon\|krs/{..}` | Surowe wyszukiwanie (bez dat). |
| GET | `/report/{regon}?report_name=..` | Surowy pełny raport GUS. |

Parametry endpointów `/entity` i `/entities`:
- `format=json` (domyślnie) lub `format=csv` — CSV do zaciągnięcia w Excelu.
- `raw=true` — dołącza surowe dane GUS (tylko `/entity/...`).
- `sep=;` — separator kolumn w CSV (domyślnie `;`, pod polski Excel).

Ujednolicony rekord zawiera m.in.: `nazwa`, `nip`, `regon`, adres, **`status`**
oraz daty: `data_powstania`, `data_rozpoczecia_dzialalnosci`,
`data_zawieszenia_dzialalnosci`, `data_wznowienia_dzialalnosci`,
`data_zakonczenia_dzialalnosci`, `data_skreslenia_z_regon`.

Pole **`status`** (wyliczane z dat, wygodne do CRM) przyjmuje wartości:
- `aktywna` — działalność prowadzona,
- `zawieszona` — jest data zawieszenia bez późniejszego wznowienia,
- `zamknieta` — jest data zakończenia działalności lub skreślenia z REGON.

### Przykłady

```bash
# Ujednolicone dane z datami (JSON)
curl -H "X-API-Key: sekret" http://localhost:8000/entity/nip/5261040828

# To samo jako CSV (Excel)
curl -H "X-API-Key: sekret" "http://localhost:8000/entity/nip/5261040828?format=csv"

# Wsadowo wiele podmiotów do CSV
curl -H "X-API-Key: sekret" "http://localhost:8000/entities?nip=5261040828&regon=000331501&format=csv"

# Surowy pełny raport
curl -H "X-API-Key: sekret" "http://localhost:8000/report/000331501?report_name=BIR11OsPrawna"
```

### Pobieranie danych do Excela (Power Query)

1. W Excelu: **Dane → Pobierz dane → Z innych źródeł → Z sieci Web**.
2. Wklej URL, np. `https://gus.twojadomena.pl/entities?nip=5261040828&regon=000331501&format=csv`.
3. Rozwiń **Zaawansowane** i dodaj nagłówek HTTP: `X-API-Key` = Twój sekret.
4. Zatwierdź — dane wpadną do arkusza. Przycisk **Odśwież** pobierze je ponownie.

> Alternatywnie `format=json` — Power Query sparsuje też JSON. CSV jest
> najprostszy do tabelarycznego widoku.

### Przydatne nazwy raportów (BIR 1.1)

- `BIR11OsFizycznaDaneOgolne`
- `BIR11OsFizycznaDzialalnoscCeidg`
- `BIR11OsPrawna`
- `BIR11OsPrawnaPkd`
- `BIR11JednLokalnaOsPrawnej`

(Pełna lista w dokumentacji GUS BIR.)

## Uruchomienie bez Dockera

```bash
pip install -r requirements.txt
export GUS_API_KEY=abcde12345abcde12345
uvicorn app.main:app --reload
```

## Wersje BIR

Ustawiane przez `GUS_BIR_VERSION`. Biblioteka RegonAPI obsługuje **`bir1`** (BIR 1.0)
oraz **`bir1.1`** — `bir1.2` **nie istnieje** w tej bibliotece i ustawienie go
powoduje błąd logowania. Domyślnie i zalecane: `bir1.1` (aktualne produkcyjne
API GUS). Pamiętaj, że **klucz użytkownika bywa przypisany do konkretnej wersji**
po stronie GUS.

## Uwagi

- Proxy trzyma jedną sesję GUS i **automatycznie loguje się ponownie**, gdy sesja
  wygaśnie (GUS unieważnia `sid` po ok. 60 min bezczynności).
- GUS ma limity zapytań — nie zdejmuj cache’a po swojej stronie, jeśli robisz
  dużo odpytań.
- Nazwy pól z datami warto potwierdzić „na żywo"
  (`/entity/nip/<nip>?raw=true`) przy pierwszym uruchomieniu na danej wersji.

## Licencja

[MIT](LICENSE) — możesz swobodnie używać, modyfikować i rozpowszechniać, bez
gwarancji.
