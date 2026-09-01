"""Async wrapper around the synchronous `edgar` (EdgarTools) SEC EDGAR library.

EdgarTools makes blocking HTTP calls under the hood and has no async API, so every call here
runs through `asyncio.to_thread`. It's also unauthenticated but requires a per-request identity
string (SEC fair-access policy), set once via `edgar.set_identity()`.
"""

import asyncio
from typing import Literal

import edgar
import pybreaker

from agentdrops.config import Settings
from agentdrops.resilience.circuit_breaker import call_with_breaker, get_breaker

EdgarDataType = Literal["10-K", "10-Q", "8-K", "financials", "insider_trades", "13F"]

_EXCERPT_CHARS = 3000
_TABLE_CHARS = 4000

_identity_set = False


def _ensure_identity(settings: Settings) -> None:
    global _identity_set
    if not _identity_set:
        edgar.set_identity(settings.edgar_identity)
        _identity_set = True


class EdgarToolError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(f"[edgar] {message}")


def _format_recent_filings(ticker: str, form: str, limit: int) -> str:
    filings = edgar.Company(ticker).get_filings(form=form).head(limit)
    if len(filings) == 0:
        return f"No {form} filings found for {ticker}."
    blocks = [
        f"FORM {filing.form} — {filing.company} ({ticker})\n"
        f"Filed: {filing.filing_date}\n"
        f"Accession: {filing.accession_no}\n"
        f"URL: {filing.homepage_url}\n"
        f"EXCERPT:\n{filing.text()[:_EXCERPT_CHARS]}"
        for filing in filings
    ]
    return "\n\n".join(blocks)


def _format_financials(ticker: str) -> str:
    financials = edgar.Company(ticker).get_financials()
    if financials is None:
        return f"No financial statements found for {ticker}."
    statements = {
        "INCOME STATEMENT": financials.income_statement(),
        "BALANCE SHEET": financials.balance_sheet(),
        "CASH FLOW STATEMENT": financials.cash_flow_statement(),
    }
    blocks = [
        f"{label} ({ticker}):\n{statement.to_dataframe().to_string(index=False)[:_TABLE_CHARS]}"
        for label, statement in statements.items()
        if statement is not None
    ]
    if not blocks:
        return f"No financial statements found for {ticker}."
    return "\n\n".join(blocks)


def _format_insider_trades(ticker: str, limit: int) -> str:
    filings = edgar.Company(ticker).get_filings(form="4").head(limit)
    if len(filings) == 0:
        return f"No Form 4 insider transactions found for {ticker}."
    blocks = [
        f"Form 4 filed {filing.filing_date} (accession {filing.accession_no}):\n"
        f"{filing.obj().to_dataframe().to_string(index=False)[:_TABLE_CHARS]}"
        for filing in filings
    ]
    return "\n\n".join(blocks)


def _format_institutional_holdings(ticker: str) -> str:
    filing = edgar.Company(ticker).get_filings(form="13F-HR").latest()
    if filing is None:
        return f"No 13F-HR institutional holdings filing found for {ticker}."
    holdings = filing.obj().holdings
    return (
        f"13F-HR holdings filed {filing.filing_date} by {filing.company} "
        f"(accession {filing.accession_no}):\n{holdings.to_string(index=False)[:_TABLE_CHARS]}"
    )


def _fetch(ticker: str, data_type: EdgarDataType, limit: int) -> str:
    if data_type in ("10-K", "10-Q", "8-K"):
        return _format_recent_filings(ticker, data_type, limit)
    if data_type == "financials":
        return _format_financials(ticker)
    if data_type == "insider_trades":
        return _format_insider_trades(ticker, limit)
    return _format_institutional_holdings(ticker)


async def fetch_edgar_data(
    settings: Settings, ticker: str, data_type: EdgarDataType, limit: int
) -> str:
    """Fetch and format one kind of SEC EDGAR data for `ticker`. Never raises for a data-side
    "not found" (returns a plain message instead); raises `EdgarToolError` for anything that
    means the request itself failed (bad ticker, breaker open, library error)."""
    _ensure_identity(settings)
    breaker = get_breaker("edgar", fail_max=5, reset_timeout=60)
    try:
        return await call_with_breaker(
            breaker, asyncio.to_thread, _fetch, ticker, data_type, limit
        )
    except pybreaker.CircuitBreakerError as exc:
        raise EdgarToolError("circuit open: edgar unavailable") from exc
    except Exception as exc:
        raise EdgarToolError(f"{ticker} {data_type}: {exc}") from exc
