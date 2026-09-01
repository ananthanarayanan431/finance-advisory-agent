import pytest

import agentdrops.agents.edgar.client as edgar_client
from agentdrops.resilience.circuit_breaker import _breakers


@pytest.fixture(autouse=True)
def _reset_edgar_module_state() -> None:
    _breakers.clear()
    edgar_client._identity_set = False
