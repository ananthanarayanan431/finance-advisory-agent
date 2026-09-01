"""Adapts SEC EDGAR data (via `edgar/client.py`) into a LangChain tool, the same shape as
agents/tools.py::make_tavily_tool / agents/contexthub/tools.py::make_context_hub_tool."""

from typing import Literal

from langchain_core.tools import BaseTool, tool

from agentdrops.agents.edgar.client import fetch_edgar_data
from agentdrops.config import Settings


def make_edgar_tool(settings: Settings) -> BaseTool:
    @tool
    async def edgar_search(
        ticker: str,
        data_type: Literal["10-K", "10-Q", "8-K", "financials", "insider_trades", "13F"],
        limit: int = 3,
    ) -> str:
        """Look up SEC EDGAR data for a public company by ticker symbol.

        `data_type`:
        - "10-K" / "10-Q" / "8-K": the `limit` most recent filings of that type, each with a
          text excerpt.
        - "financials": income statement, balance sheet, and cash flow statement.
        - "insider_trades": the `limit` most recent Form 4 insider transactions.
        - "13F": the company's latest 13F-HR institutional holdings filing.

        Prefer this over web search whenever the topic needs SEC-filed facts — reported
        financials, insider trading activity, or institutional ownership — for a company with a
        known ticker. Falls back to a plain "not found" message rather than erroring when a
        company has no filings of the requested type.
        """
        return await fetch_edgar_data(settings, ticker, data_type, limit)

    return edgar_search
