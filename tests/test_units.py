import pytest

from reaper_mcp.units import SILENCE_DB, db_to_linear, linear_to_db


@pytest.mark.parametrize("db", [-60.0, -6.0, 0.0, 6.0, 12.0])
def test_round_trip(db):
    assert linear_to_db(db_to_linear(db)) == pytest.approx(db)


def test_silence_is_a_number_not_infinity():
    assert db_to_linear(SILENCE_DB) == 0.0
    assert db_to_linear(-200.0) == 0.0
    assert linear_to_db(0.0) == SILENCE_DB
    assert linear_to_db(1e-12) == SILENCE_DB
