"""Tests for FPL's sell-price rule.

You keep only half of any price rise, rounded down to the nearest £0.1m;
falls are absorbed in full. Approximating this with the current price gives
back money that FPL would have kept, which compounds across a season of
transfers and quietly inflates any backtest built on it.
"""
import pytest

from fpl_optimizer.transfer import sell_price


class TestSellPrice:
    def test_unchanged_price_sells_at_face_value(self):
        assert sell_price(50, 50) == 50

    @pytest.mark.parametrize("buy,current", [(50, 45), (120, 100), (40, 39)])
    def test_falls_are_absorbed_in_full(self, buy, current):
        assert sell_price(buy, current) == current

    @pytest.mark.parametrize("buy,current,expected", [
        (50, 52, 51),    # +0.2 rise -> keep 0.1
        (50, 54, 52),    # +0.4 rise -> keep 0.2
        (50, 60, 55),    # +1.0 rise -> keep 0.5
        (120, 131, 125), # +1.1 rise -> keep 0.5 (rounded down)
    ])
    def test_half_of_a_rise_is_kept(self, buy, current, expected):
        assert sell_price(buy, current) == expected

    @pytest.mark.parametrize("buy,current", [(50, 51), (50, 53), (75, 78)])
    def test_odd_rises_round_down_in_fpls_favour(self, buy, current):
        rise = current - buy
        assert sell_price(buy, current) == buy + rise // 2

    def test_never_returns_more_than_the_market_price(self):
        for buy in range(38, 140, 3):
            for current in range(38, 140, 3):
                assert sell_price(buy, current) <= max(buy, current)

    def test_profit_is_never_more_than_half_the_rise(self):
        for buy in range(40, 130, 7):
            for current in range(buy, 140, 3):
                profit = sell_price(buy, current) - buy
                assert 0 <= profit <= (current - buy) / 2
