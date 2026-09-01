from unittest.mock import AsyncMock, patch

from agentdrops.agents.edgar.tools import make_edgar_tool
from tests.unit.agents.conftest import make_settings


async def test_edgar_search_tool_delegates_to_fetch_edgar_data() -> None:
    settings = make_settings()
    tool = make_edgar_tool(settings)

    assert tool.name == "edgar_search"

    with patch(
        "agentdrops.agents.edgar.tools.fetch_edgar_data",
        AsyncMock(return_value="FORM 10-K — Apple Inc. ..."),
    ) as fetch:
        result = await tool.ainvoke(
            {"ticker": "AAPL", "data_type": "10-K", "limit": 2}
        )

    fetch.assert_awaited_once_with(settings, "AAPL", "10-K", 2)
    assert result == "FORM 10-K — Apple Inc. ..."


async def test_edgar_search_tool_defaults_limit_to_three() -> None:
    settings = make_settings()
    tool = make_edgar_tool(settings)

    with patch(
        "agentdrops.agents.edgar.tools.fetch_edgar_data",
        AsyncMock(return_value="..."),
    ) as fetch:
        await tool.ainvoke({"ticker": "TSLA", "data_type": "financials"})

    fetch.assert_awaited_once_with(settings, "TSLA", "financials", 3)
