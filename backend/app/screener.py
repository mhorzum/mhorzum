"""Tarayıcı: güvenli ifade dili ve tarama çalıştırma.

Örnek ifadeler:
    rsi14 < 30 and close > sma200
    cross_up(ema20, ema50) ve rel_volume > 2
    close > prev(hh20) and adx14 > 25
    price > sma50 * 1.02

İfadeler Python sözdizimiyle ayrıştırılır ama yalnızca izin verilen düğümler
(karşılaştırma, mantıksal ve aritmetik işlemler, sayılar, alan adları ve
aşağıdaki fonksiyonlar) çalıştırılır; başka hiçbir kod çalıştırılamaz.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, field

from . import db
from .markets import check_timeframe
from .snapshot import FIELDS

FUNCTIONS = {
    "cross_up": "cross_up(a, b): a, b'yi aşağıdan yukarı kesti",
    "cross_down": "cross_down(a, b): a, b'yi yukarıdan aşağı kesti",
    "prev": "prev(x): x'in bir önceki bardaki değeri",
    "abs": "abs(x): mutlak değer",
    "min": "min(a, b, ...)",
    "max": "max(a, b, ...)",
}

_CMP = {
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
}
_BIN = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b if b else None,
    ast.Mod: lambda a, b: a % b if b else None,
}


class ExprError(ValueError):
    pass


@dataclass
class Compiled:
    text: str
    tree: ast.Expression
    fields: list[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    t = text.strip()
    t = re.sub(r"\bve\b", " and ", t, flags=re.IGNORECASE)
    t = re.sub(r"\bveya\b", " or ", t, flags=re.IGNORECASE)
    t = re.sub(r"\bdeğil\b", " not ", t, flags=re.IGNORECASE)
    t = t.replace("&&", " and ").replace("||", " or ")
    t = re.sub(r"(?<![<>=!])=(?!=)", "==", t)  # tek '=' -> '=='
    return t


def compile_expr(text: str) -> Compiled:
    if not text or not text.strip():
        raise ExprError("İfade boş olamaz")
    if len(text) > 1000:
        raise ExprError("İfade çok uzun")
    src = _normalize(text)
    try:
        tree = ast.parse(src, mode="eval")
        names: list[str] = []
        _validate(tree.body, names)
    except SyntaxError as e:
        raise ExprError(f"Sözdizimi hatası: {e.msg} (konum {e.offset})") from None
    except RecursionError:
        raise ExprError("İfade çok fazla iç içe") from None
    return Compiled(text, tree, list(dict.fromkeys(names)))


def _validate(node: ast.AST, names: list[str]) -> None:
    if isinstance(node, ast.BoolOp):
        for v in node.values:
            _validate(v, names)
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
        _validate(node.operand, names)
    elif isinstance(node, ast.Compare):
        if not all(type(op) in _CMP for op in node.ops):
            raise ExprError("Desteklenmeyen karşılaştırma")
        _validate(node.left, names)
        for c in node.comparators:
            _validate(c, names)
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in _BIN:
            raise ExprError("Desteklenmeyen işlem (yalnızca + - * / %)")
        _validate(node.left, names)
        _validate(node.right, names)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExprError(f"Yalnızca sayı sabitleri kullanılabilir: {node.value!r}")
    elif isinstance(node, ast.Name):
        if node.id not in FIELDS:
            close = [f for f in FIELDS if f.startswith(node.id[:3])][:5]
            hint = f" Benzer alanlar: {', '.join(close)}" if close else ""
            raise ExprError(f"Bilinmeyen alan: {node.id}.{hint}")
        names.append(node.id)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            raise ExprError("Bilinmeyen fonksiyon. Kullanılabilir: " + ", ".join(FUNCTIONS))
        if node.keywords:
            raise ExprError("Fonksiyonlarda isimli argüman kullanılamaz")
        fn, n = node.func.id, len(node.args)
        if fn in ("cross_up", "cross_down") and n != 2:
            raise ExprError(f"{fn} iki argüman alır")
        if fn in ("prev", "abs") and n != 1:
            raise ExprError(f"{fn} tek argüman alır")
        if fn in ("min", "max") and n < 2:
            raise ExprError(f"{fn} en az iki argüman alır")
        for a in node.args:
            _validate(a, names)
    else:
        raise ExprError(f"İzin verilmeyen ifade: {ast.unparse(node)}")


def _num(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _eval(node: ast.AST, cur: dict, prev: dict):
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for v in node.values:
                if not _eval(v, cur, prev):
                    return False
            return True
        for v in node.values:
            if _eval(v, cur, prev):
                return True
        return False
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, cur, prev)
        if isinstance(node.op, ast.Not):
            return not v
        if v is None:
            return None
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.Compare):
        left = _num(_eval(node.left, cur, prev))
        for op, comp in zip(node.ops, node.comparators):
            right = _num(_eval(comp, cur, prev))
            if left is None or right is None or not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BinOp):
        a, b = _num(_eval(node.left, cur, prev)), _num(_eval(node.right, cur, prev))
        if a is None or b is None:
            return None
        return _BIN[type(node.op)](a, b)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return _num(cur.get(node.id))
    if isinstance(node, ast.Call):
        fn, args = node.func.id, node.args
        if fn in ("cross_up", "cross_down"):
            a1, b1 = _num(_eval(args[0], cur, prev)), _num(_eval(args[1], cur, prev))
            a0, b0 = _num(_eval(args[0], prev, prev)), _num(_eval(args[1], prev, prev))
            if None in (a0, b0, a1, b1):
                return False
            return (a0 <= b0 and a1 > b1) if fn == "cross_up" else (a0 >= b0 and a1 < b1)
        if fn == "prev":
            return _eval(args[0], prev, prev)
        vals = [_num(_eval(a, cur, prev)) for a in args]
        if any(v is None for v in vals):
            return None
        if fn == "abs":
            return abs(vals[0])
        return min(vals) if fn == "min" else max(vals)
    raise ExprError("geçersiz düğüm")  # _validate'den geçtiyse buraya gelinmez


def evaluate(compiled: Compiled, cur: dict, prev: dict | None = None) -> bool:
    return bool(_eval(compiled.tree.body, cur, prev or {}))


# ---------------------------------------------------------------- çalıştırma
def load_candidates(timeframe: str, markets: list[str] | None = None, indexes: list[str] | None = None,
                    watchlist_id: int | None = None, symbol_ids: list[int] | None = None) -> list[dict]:
    check_timeframe(timeframe)
    sql = """
        SELECT s.id AS symbol_id, s.market, s.exchange, s.ticker, s.name, s.sector, s.indexes,
               n.bar_time, n.vals, n.prev, q.price AS live_price, q.change_pct AS live_change_pct,
               q.fetched_at AS live_at
        FROM indicator_snapshots n
        JOIN symbols s ON s.id = n.symbol_id
        LEFT JOIN live_quotes q ON q.symbol_id = s.id
        WHERE n.timeframe = %s AND s.active
    """
    params: list = [timeframe]
    if markets:
        sql += " AND s.market = ANY(%s)"
        params.append(markets)
    if indexes:
        sql += " AND s.indexes && %s"
        params.append(indexes)
    if watchlist_id:
        sql += " AND s.id IN (SELECT symbol_id FROM watchlist_items WHERE watchlist_id = %s)"
        params.append(watchlist_id)
    if symbol_ids is not None:
        sql += " AND s.id = ANY(%s)"
        params.append(symbol_ids)
    rows = db.fetch_all(sql, params)
    for r in rows:
        r["vals"]["price"] = r["live_price"] if r["live_price"] is not None else r["vals"].get("close")
        r["prev"]["price"] = r["prev"].get("close")
    return rows


def run_screen(expression: str, timeframe: str = "1d", markets: list[str] | None = None,
               indexes: list[str] | None = None, watchlist_id: int | None = None,
               sort_by: str | None = None, descending: bool = True, limit: int = 500) -> dict:
    compiled = compile_expr(expression)
    if sort_by and sort_by not in FIELDS:
        raise ExprError(f"Bilinmeyen sıralama alanı: {sort_by}")
    rows = load_candidates(timeframe, markets, indexes, watchlist_id)
    matches = []
    for r in rows:
        if evaluate(compiled, r["vals"], r["prev"]):
            matches.append(r)
    key = sort_by or "change_pct"

    def sort_key(r):
        v = r["vals"].get(key)
        return (v is not None, v if v is not None else 0)

    matches.sort(key=sort_key, reverse=descending)
    columns = ["close", "change_pct", "volume"] + [f for f in compiled.fields if f not in ("close", "change_pct", "volume")]
    out = [
        {
            "symbol_id": r["symbol_id"],
            "market": r["market"],
            "exchange": r["exchange"],
            "ticker": r["ticker"],
            "name": r["name"],
            "sector": r["sector"],
            "bar_time": r["bar_time"].isoformat(),
            "live_price": r["live_price"],
            "live_change_pct": r["live_change_pct"],
            "values": {c: r["vals"].get(c) for c in columns},
        }
        for r in matches[:limit]
    ]
    return {"expression": expression, "timeframe": timeframe, "scanned": len(rows),
            "count": len(matches), "columns": columns, "rows": out}
