import pytest

from scripts.run_application import build_base_url, pick_port


def test_pick_port_selects_first_free_candidate() -> None:
    occupied = {18000, 18002}
    selected = pick_port([18000, 18001, 18002], is_in_use=lambda p: p in occupied)
    assert selected == 18001


def test_pick_port_raises_when_all_ports_busy() -> None:
    with pytest.raises(RuntimeError):
        pick_port([18000, 18001], is_in_use=lambda _p: True)


def test_build_base_url() -> None:
    assert build_base_url(18000) == "http://127.0.0.1:18000"

