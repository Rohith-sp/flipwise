from pathlib import Path

import pytest

from flipwise.scenario import load_scenario

TOY = Path(__file__).parent / "fixtures" / "toy"


@pytest.fixture
def toy():
    return load_scenario(TOY)
