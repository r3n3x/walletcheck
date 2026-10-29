import pytest

import walletcheck as W


@pytest.mark.parametrize("value,shown", [
    (0, "0"),
    (1e-13, "1.00e-13 (dust)"),       # must never be displayed as 0.000000
    (0.000001, "0.000001"),
    (0.1983173, "0.198317"),
    (1.5, "1.5"),
    (500881958.442929, "500,881,958.442929"),
])
def test_fmt_amount(value, shown):
    assert W.fmt_amount(value) == shown
