"""
通用 Redis 数据池操作（基于 redis-py，同步封装）

用途：在代码用例之间传递数据。支持两种模式：

【模式1：数据池模式（推荐）】
同一个 name 下存一个「值池」，在 Redis 中以 JSON 数组形式存在：[{...}, {...}]，
每个元素是一次写入的 dict。

三个方法：
    方法1 write(name, value, expire)  写入。首次写入自动初始化为 [value]，之后追加到末尾；
                                      expire 可选，设置整个 key 的有效期（秒）
    方法2 get_latest(name, is_remove) 取最新（最后写入）的一个值；is_remove=True 取完即移除
    方法3 keys(pattern)               查询当前所有 key

【模式2：直接 key-value 模式】
直接存储单个值（非数组），适合配置、令牌等场景。

两个方法：
    方法4 write2(name, value, expire) 直接写入，会覆盖原值
    方法5 get_value(name)             直接获取完整值

两种调用方式（与 db_operate.py 一致）：
    方式一：类实例化（推荐，实例持有连接配置，多次操作不用重复传参）
        rd = RedisPool()
        # 数据池模式
        rd.write("order_pool", {"orderNo": "A1", "amount": 2.2})
        rd.get_latest("order_pool")
        # 直接 key-value 模式
        rd.write2("config", {"debug": True})
        rd.get_value("config")

    方式二：模块级函数（一次性调用）
        from common.redis import write, get_latest, write2, get_value
        write("order_pool", {"orderNo": "A1"})
        write2("token", "abc123", expire=3600)

连接配置优先级（从高到低）：
    1. RedisPool(host, port, db, password) 构造参数
    2. 环境变量 REDIS_URL=redis://[:password@]host:port/db
    3. 默认值 127.0.0.1:6379/0

用法示例：
    from common.redis import RedisPool

    rd = RedisPool()

    # 数据池模式示例
    rd.write("order_pool", {"orderNo": "A1", "amount": 2.2})   # True，池内 [{A1}]
    rd.write("order_pool", {"orderNo": "A2", "amount": 3.3})   # True，池内 [{A1},{A2}]

    # 有效期（作用在整个 key 上，到期整个池一起消失）
    rd.write("tmp_pool", {"token": "x"}, expire=60)            # 60 秒后过期
    rd.write("tmp_pool", {"token": "y"})                       # 追加，剩余有效期不变
    rd.write("tmp_pool", {"token": "z"}, expire=120)           # 重新计时 120 秒
    from datetime import timedelta
    rd.write("tmp_pool", {"token": "w"}, expire=timedelta(minutes=5))

    rd.get_latest("order_pool")                    # {"orderNo":"A2",...}，池不变
    rd.get_latest("order_pool", is_remove=True)    # {"orderNo":"A2",...}，池变 [{A1}]
    rd.get_latest("empty_pool")                    # None（key 不存在或池已空）

    rd.keys()                  # ["order_pool", ...] 当前库所有 key
    rd.keys("order_*")         # 按 pattern 过滤

    # 直接 key-value 模式示例
    rd.write2("config", {"debug": True, "timeout": 30})   # 直接写入
    rd.write2("token", "abc123", expire=3600)             # 写入并设置1小时过期
    rd.write2("counter", 100)                              # 可以存储数字

    config = rd.get_value("config")    # {"debug": True, "timeout": 30}
    token = rd.get_value("token")      # "abc123"
    counter = rd.get_value("counter")  # 100

    # 指定连接 / 隔离到独立 db，避免和后端缓存（REDIS_URL 默认 db 0）混在一起
    rd = RedisPool(host="127.0.0.1", port=6379, db=5)

注意：
  - 取值是后进先出（取最后写入的一个），与 write 追加到末尾对应。
  - 池被取空后 key 仍保留、值为 []，不会自动删除，keys() 里还能看到。
    但如果设过有效期，到期后整个 key 会被 Redis 自动删掉，keys() 里也就没了。
  - 有效期是 key 级别的，Redis 不支持给数组里的单个元素单独设过期时间。
    追加写入（不传 expire）和消费取值都不会动已设的有效期。
  - 写入/取出用 WATCH 乐观锁 + 随机退避重试，保证读-改-写是原子的：
    并发写不会互相覆盖，并发消费同一条不会被两个调用方同时取到。
    实测 10 线程各写 20 条、再并发消费，200 条不重不漏。
    代价是冲突时靠重试解决，几十个调用方死磕同一个 key 会变慢；
    这是给用例传数据用的，不是高吞吐队列。
  - 失败不抛异常：write/write2 返回 False，get_latest/get_value 返回 None，
    keys 返回 []，同时打印 [redis] 前缀的告警（与 db_operate.py 的风格一致）。
"""
import json
import os
import random
import time
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlparse

from dotenv import load_dotenv

# 本模块文件名与 redis 包同名。runner 按文件路径加载用例、sys.path 里没有本目录，
# 所以这里 import 到的是已安装的 redis-py。但若直接在本目录下执行脚本，
# 该目录会进 sys.path[0] 遮蔽真包，此时给出明确报错，而不是莫名的 AttributeError。
import redis as _redis

if not hasattr(_redis, "Redis"):
    raise ImportError(
        "import redis 拿到的是 code_testcases/common/redis.py 自身，而不是 redis-py。"
        "请不要在本目录下直接运行脚本，改到 qauto-backend 根目录执行。"
    )

# code_case runner 在 qauto-backend 目录下以子进程执行，load_dotenv 可读到 .env
load_dotenv()

# 读-改-写遇到并发冲突（WatchError）时的重试预算。
# 实测 10 线程并发写同一个 key：预算 5 次会有三分之一的写入被拒（返回 False），
# 所以给足重试次数 + 随机退避，让冲突方错开而不是同时重试。
_MAX_RETRIES = 200
# 退避基数（秒）。乘以 1~2 的随机因子，避免多个调用方同步重试形成活锁
_RETRY_BACKOFF_BASE = 0.002
_DEFAULT_SOCKET_TIMEOUT = 10


def _get_env_conn_config() -> dict:
    """从环境变量 REDIS_URL / 默认值解析连接配置。"""
    url = os.getenv("REDIS_URL", "").strip()
    if url:
        parsed = urlparse(url)
        if parsed.scheme in ("redis", "rediss"):
            path = (parsed.path or "").lstrip("/")
            return {
                "host": parsed.hostname or "127.0.0.1",
                "port": parsed.port or 6379,
                "db": int(path) if path.isdigit() else 0,
                "password": parsed.password or None,
            }
    return {"host": "127.0.0.1", "port": 6379, "db": 0, "password": None}


def _decode_pool(raw) -> list:
    """把 Redis 里的原始字符串解析成值池 list。

    key 不存在、空串、非 JSON、或 JSON 不是数组时，都当作「空池」返回 []，
    让首次写入能正常初始化，而不是因为脏数据直接报错。
    """
    if raw is None or raw == "":
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        print(f"[redis] 值不是合法 JSON，按空池处理: {str(raw)[:60]}")
        return []
    if not isinstance(parsed, list):
        print(f"[redis] 值不是 JSON 数组（当前 {type(parsed).__name__}），按空池处理")
        return []
    return parsed


class _DecimalEncoder(json.JSONEncoder):
    """自定义 JSON 编码器，支持 Decimal 类型转换为 float。"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def _encode_pool(pool: list) -> str:
    """把值池序列化成紧凑 JSON 字符串存回 Redis。"""
    return json.dumps(pool, ensure_ascii=False, separators=(",", ":"), cls=_DecimalEncoder)


def _expire_set_options(expire) -> dict:
    """把 expire 入参转成写回时给 SET 用的选项。

    关键点：Redis 的 SET 默认会清掉 key 上已有的 TTL。所以不传 expire 时必须带
    keepttl，否则「第一次写入设了 60 秒、第二次写入」会把过期时间悄悄抹掉。
    ex 与 keepttl 在 Redis 里互斥（同时传报 syntax error），这里二选一。

    Returns:
        {"ex": 秒数或 timedelta} —— 传了 expire，设置/刷新有效期
        {"keepttl": True}        —— 没传 expire，保留 key 现有的有效期
    """
    if expire is None:
        return {"keepttl": True}

    # bool 是 int 的子类，True 会被当成 1 秒，几乎肯定是误用，直接拦掉
    if isinstance(expire, bool):
        raise ValueError("expire 不能是布尔值，应为正整数秒或 timedelta")

    if isinstance(expire, timedelta):
        if expire.total_seconds() <= 0:
            raise ValueError(f"expire 必须大于 0，当前 {expire}")
        return {"ex": expire}

    if isinstance(expire, int):
        if expire <= 0:
            raise ValueError(f"expire 必须是正整数秒，当前 {expire}")
        return {"ex": expire}

    # float 不接受：Redis 的 EX 只认整数秒，传 1.5 会被静默截断成 1，容易踩坑
    raise ValueError(
        f"expire 应为正整数秒或 timedelta，当前类型 {type(expire).__name__}"
    )


class RedisPool:
    """Redis 数据池操作类。

    构造方式：
        RedisPool()                                   # 走 REDIS_URL / 默认值
        RedisPool(host="127.0.0.1", port=6379, db=5)  # 显式指定
        RedisPool(url="redis://127.0.0.1:6379/5")     # 用 URL
    """

    def __init__(self, host=None, port=None, db=None, password=None,
                 url=None, socket_timeout=_DEFAULT_SOCKET_TIMEOUT):
        """构造实例，只存连接配置，首次实际操作时才建连接。

        Args:
            host:     Redis 主机
            port:     端口（int）
            db:       库号（int），不传则用 REDIS_URL 里的库号
            password: 密码，无密码传 None
            url:      可选 redis:// URL，优先级高于环境变量、低于 host/port/db
            socket_timeout: socket 读写超时秒数
        """
        base = _get_env_conn_config()

        # url 参数覆盖环境变量
        if url:
            parsed = urlparse(url)
            path = (parsed.path or "").lstrip("/")
            base.update({
                "host": parsed.hostname or base["host"],
                "port": parsed.port or base["port"],
                "db": int(path) if path.isdigit() else base["db"],
                "password": parsed.password or base["password"],
            })

        # 显式构造参数优先级最高
        if host is not None:
            base["host"] = host
        if port is not None:
            base["port"] = int(port)
        if db is not None:
            base["db"] = int(db)
        if password is not None:
            base["password"] = password

        base["socket_timeout"] = socket_timeout
        self.conn_config = base
        self._conn = None

    def _client(self):
        """懒建 redis 客户端并复用。

        redis-py 客户端自带连接池、本身线程安全，设计上就该长期复用，
        所以这里和 db_operate「每次新建连接」的做法不同，不必每次操作重连。
        代码用例跑在短生命周期子进程里，进程退出连接自然释放。
        """
        if self._conn is None:
            # decode_responses=True：直接拿 str，省去每处手动 decode
            self._conn = _redis.Redis(decode_responses=True, **self.conn_config)
        return self._conn

    def close(self):
        """主动释放连接池。用例里通常不用调，进程退出会自动回收。"""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception as e:
                print(f"[redis] close 警告: {e}")
            finally:
                self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _atomic(self, name: str, mutate, set_options=None):
        """在 WATCH 乐观锁下执行「读值池 -> 计算 -> 写回」。

        直接 get 再 set 的话，两个用例同时写会互相覆盖、丢数据；
        WATCH 到 key 在期间被改动就重试，保证读-改-写是一个整体。
        JSON 编解码全在 Python 侧做（不用 Lua），避免数值精度被 cjson 改写。

        Args:
            name: Redis key
            mutate: 回调，入参当前值池 list，返回 (新值池 | None, 返回值)。
                    新值池为 None 表示只读、不写回。
            set_options: 写回时传给 SET 的选项，如 {"ex": 60} 或 {"keepttl": True}。
                         注意 ex 与 keepttl 在 Redis 里互斥，同时传会报 syntax error。
        """
        client = self._client()
        for _ in range(_MAX_RETRIES):
            with client.pipeline() as pipe:
                try:
                    pipe.watch(name)
                    new_pool, result = mutate(_decode_pool(pipe.get(name)))
                    if new_pool is None:
                        pipe.unwatch()
                        return result
                    pipe.multi()
                    pipe.set(name, _encode_pool(new_pool), **(set_options or {}))
                    pipe.execute()
                    return result
                except _redis.WatchError:
                    # key 被其他调用改动，退避一小会儿再重读重算。
                    # 随机因子让并发方错开，否则大家同时重试会一直互相撞
                    time.sleep(_RETRY_BACKOFF_BASE * (1 + random.random()))
                    continue
        raise _redis.RedisError(
            f"key「{name}」并发冲突，重试 {_MAX_RETRIES} 次仍失败"
        )

    # ── 方法1：写入 ──────────────────────────────────────────────
    def write(self, name, value, expire=None):
        """写入一个值到 name 对应的值池。

        首次写入时自动初始化，Redis 中存成 [value]；
        之后每次写入追加到数组末尾，成为 [{...}, {...}]。

        Args:
            name:   Redis key，自定义
            value:  要写入的值，dict，形如 {"xxx": "xxx", "xxx": "xxx"}
            expire: 有效期，可选。整数秒或 datetime.timedelta。
                    不传（默认 None）= 不动 key 现有的过期时间：
                      - key 原本没有效期  -> 一直不过期
                      - key 原本设过有效期 -> 沿用剩余时间，不会被这次写入抹掉
                    传了 = 设置/刷新整个 key 的有效期，从这次写入重新开始计时。

        Returns:
            True 成功；False 失败（参数非法或 Redis 异常，已打印告警）

        注：有效期作用在整个 key（也就是整个值池）上，Redis 不支持给数组里的
            单个元素单独设过期。到期后整个池一起消失，get_latest 返回 None。
        """
        try:
            if not name or not isinstance(name, str):
                raise ValueError("name 必须是非空字符串")
            if not isinstance(value, dict):
                raise ValueError(
                    f"value 必须是 dict，形如 {{'k': 'v'}}，当前为 {type(value).__name__}"
                )
            # 先在本地试一次序列化，尽早暴露不可序列化的值（datetime、自定义对象等），
            # 避免脏数据进到 WATCH 事务里、报错位置难定位
            json.dumps(value, ensure_ascii=False, cls=_DecimalEncoder)

            def mutate(pool):
                pool.append(value)
                return pool, True

            return self._atomic(name, mutate, _expire_set_options(expire))
        except Exception as e:
            print(f"[redis] write 执行失败: {e}")
            return False

    # ── 方法2：取最新值 ──────────────────────────────────────────
    def get_latest(self, name, is_remove=False):
        """取 name 值池里最新（最后写入）的一个值。

        Args:
            name:      Redis key
            is_remove: 默认 False，只读不动数据；
                       True 则取到的值会从池里移除（取走即消费，适合并发抢号）

        Returns:
            dict 取到的值；None 表示 key 不存在、池已空、key 已过期，
            或执行失败（已打印告警）

        注：is_remove=True 时「读取 + 移除」是一个原子操作，
            并发调用不会有两个用例拿到同一个值。
            消费不影响 key 的有效期：既不会续期，也不会把已设的有效期抹掉。
        """
        try:
            if not name or not isinstance(name, str):
                raise ValueError("name 必须是非空字符串")

            def mutate(pool):
                if not pool:
                    return None, None          # 空池：不写回，返回 None
                latest = pool[-1]
                if not is_remove:
                    return None, latest        # 只读：不写回
                return pool[:-1], latest       # 消费：去掉末尾再写回

            # keepttl：消费只是取走一个值，不该顺手把 key 的有效期抹掉或续期
            return self._atomic(name, mutate, {"keepttl": True})
        except Exception as e:
            print(f"[redis] get_latest 执行失败: {e}")
            return None

    # ── 方法3：查询所有 key ──────────────────────────────────────
    def keys(self, pattern="*"):
        """查询当前库里所有 key。

        Args:
            pattern: 匹配模式，默认 "*" 全部；也可传 "order_*" 之类过滤

        Returns:
            list[str] key 名列表（已排序）；失败返回 []（已打印告警）

        注：用 SCAN 增量遍历，不用 KEYS —— KEYS 在大库上会阻塞整个 Redis。
            默认连的是 REDIS_URL 指定的库（本项目 db 0，后端缓存也在这里），
            所以结果里会有后端自己的缓存 key。想只看用例数据，
            建议 RedisPool(db=5) 换个独立库，或用 pattern 过滤。
        """
        try:
            return sorted(self._client().scan_iter(match=pattern or "*", count=500))
        except Exception as e:
            print(f"[redis] keys 执行失败: {e}")
            return []

    # ── 方法4：直接写入 key-value（非池模式）──────────────────────
    def write2(self, name, value, expire=None):
        """直接写入一个 key-value 对（非池模式，会覆盖原值）。

        与 write() 的区别：
            write()  - 追加模式，value 追加到数组池 [{}, {}]
            write2() - 覆盖模式，直接存储 value（可以是 dict/str/int 等）

        Args:
            name:   Redis key
            value:  要写入的值，可以是 dict、str、int、list 等任意可序列化类型
            expire: 有效期，正整数秒或 timedelta；不传则永久有效

        Returns:
            True 成功；False 失败（已打印告警）

        使用示例：
            rd = RedisPool()
            rd.write2("config", {"debug": True, "timeout": 30})
            rd.write2("token", "abc123", expire=3600)
            rd.write2("counter", 100)
        """
        try:
            if not name or not isinstance(name, str):
                raise ValueError("name 必须是非空字符串")

            # 序列化为 JSON
            serialized = json.dumps(value, ensure_ascii=False, cls=_DecimalEncoder)

            # 设置到 Redis
            client = self._client()
            set_opts = _expire_set_options(expire)
            client.set(name, serialized, **set_opts)
            return True
        except Exception as e:
            print(f"[redis] write2 执行失败: {e}")
            return False

    # ── 方法5：直接获取 key 的值（非池模式）────────────────────────
    def get_value(self, name):
        """直接获取 key 对应的完整值（非池模式）。

        与 get_latest() 的区别：
            get_latest() - 从数组池中取最后一个元素
            get_value()  - 直接返回 key 的完整值

        Args:
            name: Redis key

        Returns:
            任意类型: 取决于写入时的类型（dict/str/int/list 等）
            None: key 不存在、已过期，或执行失败（已打印告警）

        使用示例：
            rd = RedisPool()
            config = rd.get_value("config")       # {"debug": True, "timeout": 30}
            token = rd.get_value("token")         # "abc123"
            counter = rd.get_value("counter")     # 100
        """
        try:
            if not name or not isinstance(name, str):
                raise ValueError("name 必须是非空字符串")

            client = self._client()
            raw = client.get(name)

            if raw is None:
                return None

            # 尝试解析 JSON
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                # 不是 JSON，直接返回原始字符串
                return raw
        except Exception as e:
            print(f"[redis] get_value 执行失败: {e}")
            return None


# =====================================================================
# 模块级函数（一次性调用，不用先实例化）
# =====================================================================
def write(name, value, expire=None, conn=None):
    """模块级：写入值池。用法参考 RedisPool.write。

    Args:
        expire: 有效期，正整数秒或 timedelta；不传则不动 key 现有的过期时间
        conn: 可选连接配置，dict 如 {"host":..,"port":..,"db":..} 或 redis:// URL 字符串
    """
    return _pool_from(conn).write(name, value, expire=expire)


def get_latest(name, is_remove=False, conn=None):
    """模块级：取最新值。用法参考 RedisPool.get_latest。"""
    return _pool_from(conn).get_latest(name, is_remove=is_remove)


def keys(pattern="*", conn=None):
    """模块级：查询所有 key。用法参考 RedisPool.keys。"""
    return _pool_from(conn).keys(pattern)


def write2(name, value, expire=None, conn=None):
    """模块级：直接写入 key-value（非池模式）。用法参考 RedisPool.write2。

    Args:
        name:   Redis key
        value:  要写入的值，任意可序列化类型
        expire: 有效期，正整数秒或 timedelta；不传则永久有效
        conn:   可选连接配置
    """
    return _pool_from(conn).write2(name, value, expire=expire)


def get_value(name, conn=None):
    """模块级：直接获取 key 的值（非池模式）。用法参考 RedisPool.get_value。

    Args:
        name: Redis key
        conn: 可选连接配置

    Returns:
        任意类型或 None
    """
    return _pool_from(conn).get_value(name)


def _pool_from(conn=None) -> RedisPool:
    """把模块级函数的 conn 参数（dict / URL / None）转成 RedisPool 实例。"""
    if conn is None:
        return RedisPool()
    if isinstance(conn, str):
        return RedisPool(url=conn)
    if isinstance(conn, dict):
        return RedisPool(**{k: v for k, v in conn.items()
                            if k in ("host", "port", "db", "password",
                                     "url", "socket_timeout")})
    raise ValueError(f"conn 应为 dict 或 URL 字符串，当前类型: {type(conn).__name__}")
