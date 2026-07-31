"""Modele odpowiedzi (Pydantic) dla proxy."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SearchResponse(BaseModel):
    count: int
    results: list[dict[str, Any]]


class ReportResponse(BaseModel):
    regon: str
    report_name: str
    results: list[dict[str, Any]]


class ErrorResponse(BaseModel):
    detail: str
