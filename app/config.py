"""Konfiguracja aplikacji ładowana ze zmiennych środowiskowych."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GUS_", env_file=".env", extra="ignore")

    # Klucz użytkownika do API GUS BIR.
    # Dla środowiska testowego GUS udostępnia publiczny klucz: abcde12345abcde12345
    api_key: str = "abcde12345abcde12345"

    # True -> środowisko produkcyjne, False -> testowe.
    production: bool = False

    # Wersja usługi obsługiwana przez RegonAPI: "bir1" albo "bir1.1".
    bir_version: str = "bir1.1"

    # Timeouty (sekundy) dla wywołań do GUS.
    timeout: int = 15
    operation_timeout: int = 15

    # Prosta ochrona proxy: jeśli ustawione, wymagany nagłówek X-API-Key.
    proxy_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
