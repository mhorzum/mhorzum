import pytest

from app.screener import ExprError, compile_expr, evaluate


def ok(expr, cur, prev=None):
    return evaluate(compile_expr(expr), cur, prev or {})


def test_basic_comparisons():
    cur = {"close": 10.0, "sma200": 8.0, "rsi14": 25.0}
    assert ok("rsi14 < 30 and close > sma200", cur)
    assert not ok("rsi14 > 30 or close < sma200", cur)
    assert ok("20 < rsi14 < 30", cur)
    assert ok("close > sma200 * 1.2", cur)
    assert ok("not close < sma200", cur)


def test_turkish_keywords_and_single_equals():
    cur = {"st_dir": 1.0, "rsi14": 40.0}
    assert ok("st_dir = 1 ve rsi14 > 30", cur)
    assert ok("st_dir = -1 veya rsi14 >= 40", cur)
    assert ok("rsi14 <= 40 && st_dir != -1", cur)


def test_missing_values_are_false():
    assert not ok("sma200 > 0", {"sma200": None})
    assert not ok("close > sma200", {"close": 5.0})
    assert not ok("close / volume > 1", {"close": 5.0, "volume": 0.0})


def test_cross_and_prev():
    prev = {"ema20": 9.0, "ema50": 10.0, "close": 9.5, "hh20": 10.0}
    cur = {"ema20": 11.0, "ema50": 10.5, "close": 10.5, "hh20": 10.5}
    assert ok("cross_up(ema20, ema50)", cur, prev)
    assert not ok("cross_down(ema20, ema50)", cur, prev)
    assert ok("close > prev(hh20)", cur, prev)
    assert ok("cross_up(close, 10)", cur, prev)
    assert ok("abs(ema20 - ema50) < 1 and max(close, 3) == close", cur, prev)


@pytest.mark.parametrize("expr", [
    "__import__('os').system('echo hi')",
    "close.real > 1",
    "(lambda: 1)()",
    "close[0] > 1",
    "'abc' == close",
    "open(1)",
    "[x for x in range(3)]",
    "close if close else 1",
    "unknown_field > 1",
    "True",
    "cross_up(close)",
    "",
])
def test_rejects_unsafe_or_invalid(expr):
    with pytest.raises(ExprError):
        compile_expr(expr)


def test_deep_nesting_rejected():
    with pytest.raises(ExprError):
        compile_expr("(" * 400 + "close" + ")" * 400 + " > 1")


def test_fields_collected():
    c = compile_expr("rsi14 < 30 and cross_up(ema20, sma50)")
    assert c.fields == ["rsi14", "ema20", "sma50"]
