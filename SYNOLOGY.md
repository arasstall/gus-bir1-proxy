# Wdrożenie na Synology (Container Manager + Reverse Proxy + HTTPS)

Ten przewodnik zakłada: build obrazu **na NAS**, klucz **produkcyjny** GUS oraz
wystawienie na internet przez **Synology Reverse Proxy z HTTPS** i ochroną
nagłówkiem **X-API-Key**.

Wymagania: DSM 7.2+ z pakietem **Container Manager**.

---

## 1. Przygotuj plik `.env` (z prawdziwymi danymi)

W folderze projektu utwórz plik `.env` (skopiuj z `.env.example`) i wpisz:

```env
GUS_API_KEY=TWOJ_PRODUKCYJNY_KLUCZ_GUS
GUS_PRODUCTION=true
GUS_BIR_VERSION=bir1.1
GUS_PROXY_API_KEY=DLUGI_LOSOWY_SEKRET
```

- `GUS_PROXY_API_KEY` to Twój własny sekret chroniący proxy — wymyśl długi,
  losowy ciąg. Klienci muszą go podawać w nagłówku `X-API-Key`.
- **Nie wysyłaj `.env` do repozytoriów** ani nikomu — zawiera klucz produkcyjny.

## 2. Wgraj projekt na NAS

W **File Station** utwórz folder, np. `docker/gus-bir1-proxy`, i wgraj do niego
całą zawartość projektu (razem z `.env`, `Dockerfile`, `docker-compose.yml`,
folderem `app/`).

## 3. Utwórz Projekt w Container Manager

1. Otwórz **Container Manager → Projekt → Utwórz**.
2. **Nazwa projektu:** `gus-bir1-proxy`.
3. **Ścieżka:** wskaż folder `docker/gus-bir1-proxy`.
4. **Źródło:** „Użyj istniejącego pliku `docker-compose.yml`" (Container Manager
   wykryje go w folderze).
5. Kliknij **Dalej / Zrób** — NAS zbuduje obraz z `Dockerfile` (pierwszy build
   trwa kilka minut) i uruchomi kontener.

> Kontener nasłuchuje na porcie `8000` na wszystkich interfejsach — dostępny w
> sieci LAN pod `http://IP_NAS-a:8000`. Ruch z internetu i tak wejdzie przez
> Reverse Proxy z HTTPS (krok 5). **Dlatego koniecznie ustaw `GUS_PROXY_API_KEY`**,
> żeby port 8000 w LAN nie był otwarty bez ochrony.

## 4. Sprawdź, że działa

W Container Manager otwórz projekt → **Logi**. Powinno pojawić się `Uvicorn
running on http://0.0.0.0:8000`. Kontener ma healthcheck — status powinien być
„zdrowy".

Test lokalny (np. z SSH na NAS, jeśli włączone):

```bash
curl -H "X-API-Key: DLUGI_LOSOWY_SEKRET" http://127.0.0.1:8000/status
```

## 5. Reverse Proxy + HTTPS w DSM

1. **Panel sterowania → Portal logowania → Zaawansowane → Reverse Proxy → Utwórz**.
2. **Źródło:**
   - Protokół: `HTTPS`
   - Nazwa hosta: np. `gus.twojadomena.pl`
   - Port: `443`
3. **Miejsce docelowe:**
   - Protokół: `HTTP`
   - Nazwa hosta: `localhost`
   - Port: `8000`
4. Zapisz.

### Certyfikat HTTPS
**Panel sterowania → Bezpieczeństwo → Certyfikat** — dodaj certyfikat Let's
Encrypt dla `gus.twojadomena.pl` i w „Ustaw domyślny certyfikat / Konfiguruj"
przypisz go do utworzonego hosta Reverse Proxy.

### DNS
Ustaw rekord DNS `gus.twojadomena.pl` na publiczny adres NAS-a i przekieruj port
`443` na routerze (jeśli za NAT-em).

## 6. Test z zewnątrz

```bash
# Powinno zadziałać (poprawny klucz)
curl -H "X-API-Key: DLUGI_LOSOWY_SEKRET" \
  https://gus.twojadomena.pl/search/nip/5261040828

# Powinno zwrócić 401 (bez klucza) — potwierdza ochronę
curl https://gus.twojadomena.pl/search/nip/5261040828
```

## 7. Aktualizacje

Po zmianie kodu: wgraj nowe pliki do folderu na NAS, potem w Container Manager
otwórz projekt → **Zbuduj** (Build) → **Uruchom ponownie**.

> **Uwaga — cache obrazu.** Samo „Zbuduj" potrafi podłączyć **stary obraz z
> cache** i zmiany nie wchodzą. Jeśli po rebuildzie kod jest stary, wymuś świeży
> build:
> 1. Projekt → **Zatrzymaj**
> 2. Zakładka **Obraz** → usuń obraz projektu (`gus-bir1-proxy:*`)
> 3. Projekt → **Zbuduj** → **Uruchom**
>
> Albo po SSH: `docker compose build --no-cache && docker compose up -d`.
>
> **Weryfikacja wersji:** `GET /health` zwraca `version` (pole `APP_VERSION`
> z `app/main.py`). Podbij tę wartość przy zmianie i sprawdź `/health` po
> rebuildzie — jeśli się nie zmieniła, nowy kod nie wszedł.

---

## Zalecenia bezpieczeństwa (internet)

- Trzymaj `GUS_PROXY_API_KEY` w tajemnicy i rotuj go okresowo.
- Rozważ włączenie zapory DSM i ograniczenie dostępu (np. geoblokada,
  lista dozwolonych IP) w **Panel sterowania → Bezpieczeństwo → Zapora**.
- Pamiętaj o limitach zapytań GUS — nie odpytuj w pętli bez potrzeby.
