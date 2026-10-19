"""
通用 HTTP 请求封装（模块级函数）

当前仅支持 POST，支持可选的 HMAC-SHA256 签名。

用法：
    from common.tec_requests import post

    # 不带签名
    res = post(url="http://xxx/api", json=body, header={"X-Foo": "bar"})

    # 带 HMAC 签名（签名头追加到 header 上，不覆盖已有 header；hmac 非必须）
    res = post(url="http://xxx/api", json=body, header={"X-Foo": "bar"},
               hmac={"appId": "XX", "appKey": "XXX"})
"""
import time
import json
import uuid
import hmac
import hashlib
from decimal import Decimal

import requests

_DEFAULT_TIMEOUT = 30


class _DecimalEncoder(json.JSONEncoder):
    """自定义 JSON 编码器，支持 Decimal 类型转换为 float。"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def _serialize_body(body) -> str:
    """将 body 序列化为紧凑 JSON 字符串，签名与发送必须使用同一份字符串。"""
    if isinstance(body, (dict, list)):
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"), cls=_DecimalEncoder)
    if body is None:
        return ""
    return str(body)

def _build_sign_headers(hmac_config, body_str: str) -> dict:
    """生成 HMAC-SHA256 签名请求头。不传 hmac_config 或缺 appId/appKey 时返回空 dict。

    签名规则（参照 apps/validator）：
        payload = appId + timestamp + nonce + body_str
        signature = HMAC-SHA256(appKey, payload).hexdigest()
    """
    if not hmac_config:
        return {}

    app_id = hmac_config.get("appId", "")
    app_key = hmac_config.get("appKey", "")
    if not app_id or not app_key:
        return {}

    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    payload = app_id + timestamp + nonce + body_str
    signature = hmac.new(
        app_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return {
        "X-App-Id": app_id,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
    }

def tec_post(url, json=None, data=None, header=None, hmac=None, timeout=_DEFAULT_TIMEOUT, **kwargs):
    """发送 POST 请求，返回解析后的 JSON（dict/list）。

    Args:
        url: 请求地址
        json: JSON 请求体（dict/list），自动序列化并参与签名
        data: 原始请求体（与 json 二选一；签名场景下建议用 json）
        header: 自定义请求头（dict）。hmac 签名头会追加进来，不会清空已有 header
        hmac: 可选签名配置 {"appId": "...", "appKey": "..."}；不传或为空则不签名
        timeout: 超时秒数
        **kwargs: 透传给 requests.post 的其他参数（如 verify、files 等）

    Returns:
        解析后的 JSON（dict/list）；响应非 JSON 时返回 {"status_code":..., "text":...}
    """
    headers = dict(header or {})

    # 确定最终发送的 body 原文，签名必须基于它
    body_str = ""
    if json is not None:
        body_str = _serialize_body(json)
        headers.setdefault("Content-Type", "application/json")
    elif isinstance(data, (dict, list)):
        body_str = _serialize_body(data)
        headers.setdefault("Content-Type", "application/json")

    # 追加签名头（不传 hmac 则跳过，不影响已有 header）
    sign_headers = _build_sign_headers(hmac, body_str)
    headers.update(sign_headers)

    # 统一使用序列化后的字符串发送，确保 Decimal 等类型被正确处理
    if body_str:
        response = requests.post(
            url, data=body_str.encode("utf-8"), headers=headers,
            timeout=timeout, **kwargs
        )
    else:
        response = requests.post(
            url, data=data, headers=headers,
            timeout=timeout, **kwargs
        )

    try:
        return response.json()
    except (json.JSONDecodeError, ValueError):
        return {"status_code": response.status_code, "text": response.text}