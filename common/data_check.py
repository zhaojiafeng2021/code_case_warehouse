"""
通用数据校验（字典对比、字段差异分析）。

提供 DataCheck 类与模块级便捷函数，用于在代码用例中对比「期望 vs 实际」。

方法概览：
    方法1 compare_dicts(src, dst, ignore_fields=None, ignore_order=False)
          对比两个数据字典（dict/list 混合结构），输出所有不一致的字段
          及其 src/dst 值。对比前做特殊处理：
              - Decimal / float / int / str("6.000000")  → 统一转 Decimal
              - datetime / date / 毫秒级整数时间戳 / 时间字符串  → 统一转毫秒时间戳（naive 值默认按 UTC+8 解释）
              - None / ""  → 视为等价（可通过参数关闭）
          支持 ignore_fields 指定跳过的字段（字段路径用 "." 嵌套，如 ["a.b.c"]）。

调用方式（与 tec_db.py / tec_redis.py 一致）：
    方式一：类实例化
        from common.data_check import DataCheck
        dc = DataCheck()
        result = dc.compare_dicts(expect, actual, ignore_fields=["update_time"])
    方式二：模块级便捷函数
        from common.data_check import compare_dicts
        result = compare_dicts(expect, actual, ignore_fields=["update_time"])
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


# ──────────────────────────────────────────────────────────────
# 内部常量
# ──────────────────────────────────────────────────────────────

# 毫秒时间戳候选整数范围(1e11 ~ 5e13 毫秒,覆盖 1973~3501 年区间):
#   秒级 10 位数 (如 1723277053)   ~ 1.7e9  < 1e11
#   毫秒 13 位数 (如 1723277053000) ~ 1.7e12  ∈ 范围
#   微秒 16 位数                   ~ 1.7e15  > 5e13 (当作普通整数)
_MS_TS_MIN = 10**11
_MS_TS_MAX = 5 * 10**13

# 默认时区：UTC+8。naive datetime / 无时区时间字符串统一按东八区解释，
# 不依赖机器本地时区（容器多为 UTC，会导致比对产生 8 小时偏差）。
_TZ_DEFAULT = _dt.timezone(_dt.timedelta(hours=8))


# ──────────────────────────────────────────────────────────────
# 辅助：单值规范化
# ──────────────────────────────────────────────────────────────

def _is_numeric_decimal(x):
    if isinstance(x, Decimal):
        return True
    if isinstance(x, bool):
        return False
    if isinstance(x, (int, float)):
        return True
    if isinstance(x, str):
        if x == "":
            return False
        try:
            Decimal(x)
            return True
        except (InvalidOperation, ValueError):
            return False
    return False


def _to_decimal(x):
    try:
        if isinstance(x, Decimal):
            return x
        if isinstance(x, (int, float)):
            return Decimal(str(x))
        if isinstance(x, str):
            return Decimal(x.strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return None
    return None


def _is_timestamp_int(x):
    if isinstance(x, bool):
        return False
    if not isinstance(x, int):
        return False
    return _MS_TS_MIN <= x <= _MS_TS_MAX


def _to_ms_timestamp(x):
    try:
        if isinstance(x, _dt.datetime):
            if x.tzinfo is not None:
                return x.timestamp() * 1000
            # naive datetime 统一按 UTC+8 处理，不依赖机器本地时区
            return x.replace(tzinfo=_TZ_DEFAULT).timestamp() * 1000
        if isinstance(x, _dt.date):
            return _dt.datetime.combine(x, _dt.time(), tzinfo=_TZ_DEFAULT).timestamp() * 1000
        if isinstance(x, bool):
            return None
        if isinstance(x, int) and _is_timestamp_int(x):
            return float(x)
        if isinstance(x, float) and _MS_TS_MIN <= x <= _MS_TS_MAX:
            return x
        if isinstance(x, str):
            s = x.strip()
            if not s:
                return None
            if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
                n = int(s)
                if _MS_TS_MIN <= n <= _MS_TS_MAX:
                    return float(n)
            for fmt in (
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d",
            ):
                try:
                    return _dt.datetime.strptime(s, fmt).replace(tzinfo=_TZ_DEFAULT).timestamp() * 1000
                except ValueError:
                    continue
            try:
                parsed = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=_TZ_DEFAULT)
                return parsed.timestamp() * 1000
            except ValueError:
                return None
    except (OverflowError, OSError, TypeError, ValueError):
        return None
    return None


def _is_time_value(x):
    if isinstance(x, (_dt.datetime, _dt.date)):
        return True
    if _is_timestamp_int(x):
        return True
    if isinstance(x, str) and x.strip():
        return _to_ms_timestamp(x) is not None
    return False


def _normalize_scalar(x, equal_none_empty, datetime_tolerance_ms):
    if x is None:
        return ("none", None)
    if isinstance(x, str) and x == "" and equal_none_empty:
        return ("none", None)
    if _is_time_value(x):
        ms = _to_ms_timestamp(x)
        if ms is not None:
            if datetime_tolerance_ms and datetime_tolerance_ms > 0:
                ms = round(ms / datetime_tolerance_ms) * datetime_tolerance_ms
            return ("datetime_ms", ms)
    if _is_numeric_decimal(x):
        d = _to_decimal(x)
        if d is not None:
            return ("decimal", d)
    if isinstance(x, bool):
        return ("bool", x)
    return ("raw", x)


# ──────────────────────────────────────────────────────────────
# 核心:两值"等价性"比较
# ──────────────────────────────────────────────────────────────

def _values_equal(a, b, *, equal_none_empty, datetime_tolerance_ms):
    cat_a, na = _normalize_scalar(a, equal_none_empty, datetime_tolerance_ms)
    cat_b, nb = _normalize_scalar(b, equal_none_empty, datetime_tolerance_ms)
    if cat_a == "none" and cat_b == "none":
        return (True, na, nb)
    cats = {cat_a, cat_b}
    if cats == {"decimal", "datetime_ms"}:
        return (False, na, nb)
    if "decimal" in cats and not (cat_a == cat_b == "decimal"):
        other = nb if cat_a == "decimal" else na
        d = _to_decimal(other if not isinstance(other, float) else str(other))
        if d is None:
            return (False, na, nb)
        if cat_a == "decimal":
            nb = d
        else:
            na = d
        try:
            return (na == nb, na, nb)
        except Exception:
            return (False, na, nb)
    if "datetime_ms" in cats and not (cat_a == cat_b == "datetime_ms"):
        other = nb if cat_a == "datetime_ms" else na
        ms = _to_ms_timestamp(other)
        if ms is None:
            return (False, na, nb)
        if datetime_tolerance_ms and datetime_tolerance_ms > 0:
            ms = round(ms / datetime_tolerance_ms) * datetime_tolerance_ms
        if cat_a == "datetime_ms":
            nb = ms
        else:
            na = ms
        try:
            return (na == nb, na, nb)
        except Exception:
            return (False, na, nb)
    if cat_a != cat_b:
        return (False, na, nb)
    try:
        return (na == nb, na, nb)
    except Exception:
        return (False, na, nb)


# ──────────────────────────────────────────────────────────────
# DataCheck 类
# ──────────────────────────────────────────────────────────────

class DataCheck:

    def __init__(self, equal_none_empty=True, datetime_tolerance_ms=None, ignore_order=True):
        self.equal_none_empty = equal_none_empty
        self.datetime_tolerance_ms = datetime_tolerance_ms
        self.ignore_order = ignore_order

    def compare_dicts(self, src, dst, ignore_fields=None, *,
                      equal_none_empty=None, datetime_tolerance_ms=..., ignore_order=None):
        if equal_none_empty is None:
            equal_none_empty = self.equal_none_empty
        if datetime_tolerance_ms is ...:
            datetime_tolerance_ms = self.datetime_tolerance_ms
        if ignore_order is None:
            ignore_order = self.ignore_order
        ig = set()
        if ignore_fields:
            for f in ignore_fields:
                if isinstance(f, str) and f:
                    ig.add(f.lstrip("."))
        if not isinstance(src, dict) or not isinstance(dst, dict):
            diffs = []
            self._compare_any(src, dst, ".", ig, diffs,
                              equal_none_empty, datetime_tolerance_ms, ignore_order, 0)
            return diffs
        diffs = []
        all_keys = self._sorted_union(src.keys(), dst.keys())
        for k in all_keys:
            path = k
            if path in ig or ("." + path) in ig:
                continue
            has_s = k in src
            has_d = k in dst
            if not has_s:
                diffs.append(self._diff(path, "missing_in_src", MISSING, dst[k],
                                        None, None, "src 缺少该字段(dst 存在)"))
                continue
            if not has_d:
                diffs.append(self._diff(path, "missing_in_dst", src[k], MISSING,
                                        None, None, "dst 缺少该字段(src 存在)"))
                continue
            self._compare_any(src[k], dst[k], path, ig, diffs,
                              equal_none_empty, datetime_tolerance_ms, ignore_order, 1)
        return diffs

    def _compare_any(self, a, b, path, ig, out,
                     equal_none_empty, datetime_tolerance_ms, ignore_order, depth):
        if path in ig:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for k in self._sorted_union(a.keys(), b.keys()):
                sub = (path + "." + k) if (path and path != ".") else k
                if sub in ig:
                    continue
                if k not in a:
                    out.append(self._diff(sub, "missing_in_src", MISSING, b[k],
                                          None, None, "src 缺少该字段"))
                    continue
                if k not in b:
                    out.append(self._diff(sub, "missing_in_dst", a[k], MISSING,
                                          None, None, "dst 缺少该字段"))
                    continue
                self._compare_any(a[k], b[k], sub, ig, out,
                                  equal_none_empty, datetime_tolerance_ms, ignore_order, depth + 1)
            return
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            if len(a) != len(b):
                out.append(self._diff(path, "length", a, b, len(a), len(b),
                                      "列表长度不一致 src=%d dst=%d" % (len(a), len(b))))
                return
            if len(a) == 0:
                return
            if ignore_order and all(self._is_scalar(x) for x in a) and all(self._is_scalar(x) for x in b):
                self._compare_scalar_list(a, b, path, ig, out,
                                          equal_none_empty, datetime_tolerance_ms)
                return
            for i, (ai, bi) in enumerate(zip(a, b)):
                sub = "%s[%d]" % (path, i)
                if sub in ig:
                    continue
                self._compare_any(ai, bi, sub, ig, out,
                                  equal_none_empty, datetime_tolerance_ms, ignore_order, depth + 1)
            return
        eq, na, nb = _values_equal(a, b,
                                   equal_none_empty=equal_none_empty,
                                   datetime_tolerance_ms=datetime_tolerance_ms)
        if not eq:
            reason = self._guess_reason(a, b, na, nb)
            out.append(self._diff(path, "value", a, b, na, nb, reason))

    def _compare_scalar_list(self, a, b, path, ig, out, equal_none_empty, datetime_tolerance_ms):
        from collections import Counter

        def norm(x):
            cat, v = _normalize_scalar(x, equal_none_empty, datetime_tolerance_ms)
            return (cat, self._hashable(v))

        def _count(xs):
            return Counter(norm(x) for x in xs)

        ca = _count(a)
        cb = _count(b)
        if ca == cb:
            return
        missing_in_b = list((ca - cb).keys())
        missing_in_a = list((cb - ca).keys())
        parts = []
        if missing_in_b:
            parts.append("src 有但 dst 缺 %d 组规范化值" % len(missing_in_b))
        if missing_in_a:
            parts.append("dst 有但 src 缺 %d 组规范化值" % len(missing_in_a))
        reason = "列表内容(忽略顺序)不一致: " + "; ".join(parts)
        out.append(self._diff(path, "list_content_set", list(a), list(b),
                              dict(ca), dict(cb), reason))

    @staticmethod
    def _is_scalar(x):
        return not isinstance(x, (dict, list, tuple))

    @staticmethod
    def _hashable(v):
        if isinstance(v, Decimal):
            return ("decimal", str(v))
        if isinstance(v, list):
            return tuple(DataCheck._hashable(x) for x in v)
        if isinstance(v, dict):
            return tuple(sorted((k, DataCheck._hashable(x)) for k, x in v.items()))
        return v

    @staticmethod
    def _sorted_union(a, b):
        ka, kb = set(a), set(b)
        allk = ka | kb
        try:
            return sorted(allk)
        except TypeError:
            return list(ka) + [x for x in kb if x not in ka]

    @staticmethod
    def _diff(field, dtype, src, dst, src_norm, dst_norm, reason):
        return {
            "field": field,
            "type": dtype,
            "src": MISSING if src is MISSING else src,
            "dst": MISSING if dst is MISSING else dst,
            "src_norm": src_norm,
            "dst_norm": dst_norm,
            "reason": reason,
        }

    @staticmethod
    def _guess_reason(a, b, na, nb):
        try:
            types = "%s vs %s" % (type(a).__name__, type(b).__name__)
        except Exception:
            types = "?"
        try:
            dec_a = isinstance(na, Decimal)
            dec_b = isinstance(nb, Decimal)
            if dec_a or dec_b:
                return "数值不一致(Decimal): %r vs %r (%s)" % (na, nb, types)
            if (isinstance(na, (int, float)) and isinstance(nb, (int, float))
                    and na is not None and nb is not None):
                try:
                    fa, fb = float(na), float(nb)
                    if _MS_TS_MIN <= fa <= _MS_TS_MAX and _MS_TS_MIN <= fb <= _MS_TS_MAX:
                        return "时间不一致:差 %g ms (%s)" % (abs(fa - fb), types)
                except (TypeError, ValueError):
                    pass
                return "数值不一致: %r vs %r (%s)" % (na, nb, types)
            return "值不一致 (%s): 规范化后 %r vs %r" % (types, na, nb)
        except Exception:
            return "值不一致 (%s)" % types


class _Missing:
    __slots__ = ()

    def __repr__(self):
        return "<MISSING>"

    def __str__(self):
        return "<MISSING>"


MISSING = _Missing()


_DC_SINGLETON = DataCheck()


def compare_dicts(src, dst, ignore_fields=None, *,
                  equal_none_empty=True, datetime_tolerance_ms=None, ignore_order=True):
    return _DC_SINGLETON.compare_dicts(
        src, dst, ignore_fields,
        equal_none_empty=equal_none_empty,
        datetime_tolerance_ms=datetime_tolerance_ms,
        ignore_order=ignore_order,
    )


__all__ = ["DataCheck", "compare_dicts", "MISSING"]
