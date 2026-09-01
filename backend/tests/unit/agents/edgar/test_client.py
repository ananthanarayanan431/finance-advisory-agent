import pandas as pd
import pytest

import agentdrops.agents.edgar.client as edgar_client
from agentdrops.agents.edgar.client import EdgarToolError, fetch_edgar_data
from tests.unit.agents.conftest import make_settings


class _FakeFiling:
    def __init__(
        self,
        *,
        form: str = "10-K",
        company: str = "Apple Inc.",
        filing_date: str = "2026-01-15",
        accession_no: str = "0000320193-26-000001",
        homepage_url: str = "https://www.sec.gov/filing/index.htm",
        text: str = "Item 1. Business. Apple designs, manufactures...",
        obj: object | None = None,
    ) -> None:
        self.form = form
        self.company = company
        self.filing_date = filing_date
        self.accession_no = accession_no
        self.homepage_url = homepage_url
        self._text = text
        self._obj = obj

    def text(self) -> str:
        return self._text

    def obj(self) -> object:
        return self._obj


class _FakeFilings:
    def __init__(self, filings: list[_FakeFiling]) -> None:
        self._filings = filings

    def head(self, n: int) -> "_FakeFilings":
        return _FakeFilings(self._filings[:n])

    def latest(self) -> _FakeFiling | None:
        return self._filings[0] if self._filings else None

    def __len__(self) -> int:
        return len(self._filings)

    def __iter__(self):
        return iter(self._filings)


class _FakeStatement:
    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def to_dataframe(self) -> pd.DataFrame:
        return self._df


class _FakeFinancials:
    def __init__(
        self,
        income: _FakeStatement | None = None,
        balance: _FakeStatement | None = None,
        cash_flow: _FakeStatement | None = None,
    ) -> None:
        self._income = income
        self._balance = balance
        self._cash_flow = cash_flow

    def income_statement(self) -> _FakeStatement | None:
        return self._income

    def balance_sheet(self) -> _FakeStatement | None:
        return self._balance

    def cash_flow_statement(self) -> _FakeStatement | None:
        return self._cash_flow


class _FakeThirteenF:
    def __init__(self, holdings: pd.DataFrame) -> None:
        self.holdings = holdings


class _FakeCompany:
    def __init__(
        self,
        filings_by_form: dict[str, _FakeFilings] | None = None,
        financials: _FakeFinancials | None = None,
    ) -> None:
        self._filings_by_form = filings_by_form or {}
        self._financials = financials

    def get_filings(self, form: str) -> _FakeFilings:
        return self._filings_by_form.get(form, _FakeFilings([]))

    def get_financials(self) -> _FakeFinancials | None:
        return self._financials


def _patch_company(monkeypatch: pytest.MonkeyPatch, company: _FakeCompany) -> None:
    monkeypatch.setattr(edgar_client.edgar, "Company", lambda ticker: company)


async def test_fetch_edgar_data_sets_identity_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(edgar_client.edgar, "set_identity", calls.append)
    _patch_company(monkeypatch, _FakeCompany({"10-K": _FakeFilings([_FakeFiling()])}))
    settings = make_settings(edgar_identity="Test Bot test@example.com")

    await fetch_edgar_data(settings, "AAPL", "10-K", 1)
    await fetch_edgar_data(settings, "AAPL", "10-K", 1)

    assert calls == ["Test Bot test@example.com"]


async def test_fetch_edgar_data_10k_includes_filing_metadata_and_excerpt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(edgar_client.edgar, "set_identity", lambda identity: None)
    filing = _FakeFiling(
        form="10-K",
        company="Apple Inc.",
        filing_date="2026-01-15",
        accession_no="0000320193-26-000001",
        text="Item 1. Business. Apple designs, manufactures and markets smartphones.",
    )
    _patch_company(monkeypatch, _FakeCompany({"10-K": _FakeFilings([filing])}))

    result = await fetch_edgar_data(make_settings(), "AAPL", "10-K", 3)

    assert "FORM 10-K" in result
    assert "Apple Inc." in result
    assert "2026-01-15" in result
    assert "0000320193-26-000001" in result
    assert "Apple designs, manufactures" in result


async def test_fetch_edgar_data_returns_not_found_message_for_no_filings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(edgar_client.edgar, "set_identity", lambda identity: None)
    _patch_company(monkeypatch, _FakeCompany())

    result = await fetch_edgar_data(make_settings(), "NOFILE", "10-Q", 3)

    assert "No 10-Q filings found for NOFILE" in result


async def test_fetch_edgar_data_financials_formats_all_statements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(edgar_client.edgar, "set_identity", lambda identity: None)
    income_df = pd.DataFrame({"Revenue": [391_035], "NetIncome": [93_736]})
    financials = _FakeFinancials(income=_FakeStatement(income_df))
    _patch_company(monkeypatch, _FakeCompany(financials=financials))

    result = await fetch_edgar_data(make_settings(), "AAPL", "financials", 1)

    assert "INCOME STATEMENT" in result
    assert "391035" in result


async def test_fetch_edgar_data_insider_trades_formats_each_form4(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(edgar_client.edgar, "set_identity", lambda identity: None)
    trades_df = pd.DataFrame({"insider": ["Tim Cook"], "shares": [1000]})
    filing = _FakeFiling(filing_date="2026-02-01", accession_no="acc-1")
    filing.obj = lambda: _FakeStatement(trades_df)  # type: ignore[method-assign]
    _patch_company(monkeypatch, _FakeCompany({"4": _FakeFilings([filing])}))

    result = await fetch_edgar_data(make_settings(), "AAPL", "insider_trades", 3)

    assert "2026-02-01" in result
    assert "Tim Cook" in result


async def test_fetch_edgar_data_13f_formats_holdings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(edgar_client.edgar, "set_identity", lambda identity: None)
    holdings_df = pd.DataFrame({"issuer": ["Apple Inc."], "value": [500_000]})
    filing = _FakeFiling(company="Berkshire Hathaway", filing_date="2026-02-14")
    filing.obj = lambda: _FakeThirteenF(holdings_df)  # type: ignore[method-assign]
    _patch_company(monkeypatch, _FakeCompany({"13F-HR": _FakeFilings([filing])}))

    result = await fetch_edgar_data(make_settings(), "BRK-A", "13F", 1)

    assert "Berkshire Hathaway" in result
    assert "Apple Inc." in result


async def test_fetch_edgar_data_wraps_library_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(edgar_client.edgar, "set_identity", lambda identity: None)

    def _raise(ticker: str) -> None:
        raise ValueError("bad ticker")

    monkeypatch.setattr(edgar_client.edgar, "Company", _raise)

    with pytest.raises(EdgarToolError, match="bad ticker"):
        await fetch_edgar_data(make_settings(), "???", "10-K", 3)


async def test_fetch_edgar_data_raises_when_circuit_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(edgar_client.edgar, "set_identity", lambda identity: None)

    def _raise(ticker: str) -> None:
        raise ValueError("edgar is down")

    monkeypatch.setattr(edgar_client.edgar, "Company", _raise)
    settings = make_settings()

    for _ in range(5):
        with pytest.raises(EdgarToolError):
            await fetch_edgar_data(settings, "AAPL", "10-K", 3)

    with pytest.raises(EdgarToolError, match="circuit open"):
        await fetch_edgar_data(settings, "AAPL", "10-K", 3)
