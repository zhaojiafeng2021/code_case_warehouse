"""
PowerJob API 工具类（自动登录态管理 + Redis 缓存）

用途：封装 PowerJob 接口调用，自动管理登录态（JWT token），
token 存 Redis，通过 TTL 控制有效期，过期后自动重新登录。

用法：
    from common.tec_powerjob import PowerJobClient

    # 实例化时只传账号，密码自动从凭证表获取
    client = PowerJobClient(username="admin")
    # 也可以显式传密码（跳过凭证查询）
    client = PowerJobClient(username="admin", password="password123")

    # 调用接口，自动带上登录态
    result = client.get("/app/list", params={"index": 0, "size": 10})
    result = client.post("/instance/stop", json={"instanceId": 123})

注意：
  - token 存储在 Redis key "powerjob:jwt:{username}" 下，TTL 6 小时
  - 登录态失效机制：依赖 Redis TTL，从 Redis 获取不到 token 时自动重新登录
  - 首次使用或 token 过期后，会自动调用登录接口获取新 token
  - 支持自定义 base_url、timeout 等参数
"""
import time
from typing import Optional

import requests

from common.tec_redis import RedisPool
from common.credential_helper import get_account_password


# 默认配置
_DEFAULT_BASE_URL = "https://powerjob-dev01.tec-develop.cn"
_DEFAULT_TIMEOUT = 30
_TOKEN_EXPIRE_SECONDS = 6 * 3600  # token 在 Redis 里的有效期，6 小时
_REDIS_KEY_PREFIX = "powerjob:jwt:"    # Redis key 前缀


class PowerJobClient:
    """PowerJob API 客户端，自动管理登录态。

    构造方式：
        PowerJobClient(username="admin")              # 密码自动从凭证表获取
        PowerJobClient(username="admin", password="pwd123")  # 显式传密码
        PowerJobClient(username="admin", base_url="https://powerjob-prod.example.com")
    """

    def __init__(
        self,
        username: str,
        password: Optional[str] = None,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: int = _DEFAULT_TIMEOUT,
        redis_conn=None,
    ):
        """初始化 PowerJob 客户端。

        Args:
            username: PowerJob 登录账号
            password: PowerJob 登录密码，不传则自动从 system_credentials 表获取
                      （system="job", type="account_password"）
            base_url: PowerJob 服务域名，默认 dev01 环境
            timeout: 请求超时秒数
            redis_conn: Redis 连接配置（dict / URL / None），None 时用环境变量
        """
        if not username:
            raise ValueError("username 不能为空")

        # 未传密码时，从凭证表自动获取
        if not password:
            cred = get_account_password(system="job", account=username)
            if not cred:
                raise ValueError(
                    f"未找到 PowerJob 账号凭证: system=job, account={username}。"
                    f"请检查 system_credentials 表中是否存在对应记录，"
                    f"且 type='account_password', is_active=true"
                )
            password = cred["password"]

        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._redis = RedisPool() if redis_conn is None else RedisPool(**redis_conn)
        self._redis_key = f"{_REDIS_KEY_PREFIX}{username}"

    def _get_token_from_redis(self) -> Optional[str]:
        """从 Redis 中获取缓存的 token。"""
        try:
            token = self._redis.get_value(self._redis_key)
            return token if token else None
        except Exception as e:
            print(f"[powerjob] 从 Redis 获取 token 失败: {e}")
            return None

    def _save_token_to_redis(self, token: str):
        """将 token 保存到 Redis，并设置有效期。"""
        try:
            self._redis.write2(self._redis_key, token, expire=_TOKEN_EXPIRE_SECONDS)
        except Exception as e:
            print(f"[powerjob] 保存 token 到 Redis 失败: {e}")

    def _login(self) -> str:
        """调用登录接口获取 jwtToken。

        Returns:
            jwtToken 字符串

        Raises:
            RuntimeError: 登录失败时抛出
        """
        import json as json_module

        login_url = f"{self.base_url}/auth/thirdPartyLoginDirect"

        # 构造实际的登录参数格式
        origin_params = json_module.dumps({
            "username": self.username,
            "password": self.password,
            "encryption": "none"
        }, ensure_ascii=False)

        payload = {
            "loginType": "PWJB",
            "originParams": origin_params
        }

        try:
            resp = requests.post(login_url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()

            # 根据实际响应结构解析
            if not data.get("success"):
                raise RuntimeError(f"登录失败: {data.get('message', '未知错误')}")

            token = data.get("data", {}).get("jwtToken")
            if not token:
                raise RuntimeError(f"登录响应中未找到 jwtToken: {data}")

            print(f"[powerjob] 用户 {self.username} 登录成功")
            return token
        except requests.RequestException as e:
            raise RuntimeError(f"登录请求失败: {e}") from e

    def _ensure_token(self) -> str:
        """确保有可用的 token，优先从 Redis 读取，不存在则登录获取。

        登录态失效机制：
        - Redis 中有 token → 直接返回（说明在 6 小时有效期内）
        - Redis 中无 token → 重新登录获取（首次使用或已过期）

        Returns:
            可用的 jwtToken
        """
        token = self._get_token_from_redis()
        if token:
            return token

        # Redis 中无 token（过期或首次使用），执行登录
        print(f"[powerjob] Redis 中无有效 token，正在重新登录...")
        token = self._login()
        self._save_token_to_redis(token)
        return token

    def _request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> dict:
        """内部请求方法，自动带上登录态。

        登录态管理：每次请求前通过 _ensure_token() 获取 token，
        该方法会自动处理 token 过期（Redis TTL）的情况。

        Args:
            method: HTTP 方法，如 "GET"、"POST"
            path: 接口路径，如 "/app/list"（会自动拼接 base_url）
            **kwargs: 透传给 requests.request 的其他参数（json、params、data 等）

        Returns:
            解析后的 JSON 响应体（dict）

        Raises:
            RuntimeError: 请求失败时抛出
        """
        token = self._ensure_token()
        url = f"{self.base_url}{path}"

        # 设置请求头，将 jwtToken 放在 powerjwt 字段
        headers = kwargs.pop("headers", {}) or {}
        headers["powerjwt"] = token
        kwargs.setdefault("timeout", self.timeout)

        try:
            resp = requests.request(method, url, headers=headers, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            raise RuntimeError(f"请求失败 {method} {url}: {e}") from e

    # ── 公开方法：GET/POST 请求 ──────────────────────────────────
    def get(self, path: str, params=None, **kwargs) -> dict:
        """发送 GET 请求。

        Args:
            path: 接口路径，如 "/app/list"
            params: 查询参数（dict）
            **kwargs: 其他参数透传给 requests（如 headers、timeout）

        Returns:
            解析后的 JSON 响应（dict）
        """
        return self._request("GET", path, params=params, **kwargs)

    def post(self, path: str, json=None, data=None, **kwargs) -> dict:
        """发送 POST 请求。

        Args:
            path: 接口路径，如 "/instance/stop"
            json: JSON 请求体（dict）
            data: 表单数据或原始请求体
            **kwargs: 其他参数透传给 requests

        Returns:
            解析后的 JSON 响应（dict）
        """
        return self._request("POST", path, json=json, data=data, **kwargs)

    def put(self, path: str, json=None, data=None, **kwargs) -> dict:
        """发送 PUT 请求。"""
        return self._request("PUT", path, json=json, data=data, **kwargs)

    def delete(self, path: str, **kwargs) -> dict:
        """发送 DELETE 请求。"""
        return self._request("DELETE", path, **kwargs)

    def refresh_token(self):
        """强制刷新 token（重新登录并更新 Redis 缓存，重置 6 小时有效期）。

        适用场景：手动强制刷新 token，无需等待 Redis TTL 过期。
        """
        print(f"[powerjob] 手动刷新 token...")
        token = self._login()
        self._save_token_to_redis(token)
        return token


