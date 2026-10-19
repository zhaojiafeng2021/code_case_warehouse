"""
通用数据库操作（基于 PyMySQL，适配 MySQL，同步封装）

两种调用方式：
  方式一：DB 类实例化（推荐）——实例持有连接配置，多次操作不用重复传参
      db = DB(host, port, user, password, db)
      result = db.query("select ...")
      # 或链式调用
      result = DB(host, port, user, password, db).query("select ...")
  方式二：模块级函数（向后兼容，参数传 conn 覆盖）
      result = query("select ...", conn={...})

连接配置优先级（从高到低）：
  1. DB(host, port, user, password, db) 构造参数 / 方法 conn 参数
  2. 环境变量 DATABASE_URL=mysql://user:pwd@host:port/db
  3. 环境变量 MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE
  4. 默认值 root@127.0.0.1:3306/auto_test_platform（本地开发）
连接生命周期：每次执行单独 connect，执行完立即主动关闭（cursor.close + conn.close），
             不复用、不缓存连接，防止连接池超上限。

用法示例：
    from common.db_operate import DB

    # 方式一：先实例化，再调用（同一个 db 实例可重复使用
    db = DB(host="127.0.0.1", port=3306, user="root", password="", database="auto_test_platform")
    rows = db.query("select * from users where id = 1")     # [{}, {}]
    ok   = db.insert("insert into users(name) values('tom')")   # True/False
    ok   = db.update("update users set name='jerry' where id=1")
    ok   = db.delete("delete from users where id=1")

    # 方式二：链式（一次性调用
    rows = DB("127.0.0.1", 3306, "root", "", "auto_test_platform").query("select * from users limit 3")

    # 方式三：不传参数（走环境变量 / 默认值
    from common.db_operate import query
    rows = query("select * from users limit 3")

    # 查询 + 重试：结果为空时重查，最多 rerun 次，每次间隔 reruntime 秒
    rows = db.query("select * from orders where status='paid'", rerun=3, reruntime=2)
"""
import os
import re
import time
from urllib.parse import urlparse

import pymysql
from pymysql.cursors import DictCursor
from dotenv import load_dotenv

# code_case runner 在 qauto-backend 目录下以子进程执行，load_dotenv 可读到 .env
load_dotenv()

# pymysql.connect 支持的连接参数键（用于校验 conn dict 合法性）
_ALLOWED_CONN_KEYS = {"host", "port", "user", "password", "database",
                      "charset", "connect_timeout", "read_timeout", "write_timeout"}


def _parse_conn_url(url: str) -> dict:
    """把 mysql://user:pwd@host:port/db 解析成连接参数 dict。"""
    normalized = re.sub(r"^mysql\+\w+://", "mysql://", url)
    parsed = urlparse(normalized)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": parsed.username or "root",
        "password": parsed.password or "",
        "database": (parsed.path or "/").lstrip("/") or "mysql",
    }


def _get_env_conn_config() -> dict:
    """从环境变量/默认值解析连接配置（不包含调用时传入的参数）。"""
    # DATABASE_URL 环境变量
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        normalized = re.sub(r"^mysql\+\w+://", "mysql://", url)
        if normalized.startswith("mysql://"):
            return _parse_conn_url(normalized)
    # MYSQL_* 环境变量 / 默认值
    return {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "database": os.getenv("MYSQL_DATABASE", "auto_test_platform"),
    }


class DB:
    """数据库操作类。

    支持两种构造方式：
        # 位置参数：DB(host, port, user, password, database)
            —— 用户要求的调用形式，参数名按用户要求：
            DB(host="127.0.0.1", port=3306, user="root", password="", db="auto_test_platform")
        # 或 URL / dict：
            DB(conn="mysql://root:@127.0.0.1:3306/auto_test_platform")
            DB(conn={"host":"127.0.0.1","port":3306,"user":"root","password":"","database":"auto_test_platform"})
        # 或不传任何参数（走环境变量 / 默认值）：
            DB()
    """

    def __init__(self, host=None, port=None, user=None, password=None, db=None,
                 database=None, conn=None, **kwargs):
        """构造 DB 实例，存入连接配置。

        Args:
            host:     数据库主机
            port:     端口（int）
            user:     用户名
            password: 密码
            db:       数据库名（用户习惯写法，等价于 database）
            database: 数据库名（标准写法，与 db 二选一，传了则以 database 为准）
            conn:     可选 dict 或 URL 字符串（优先级高于 host/port/...）
            **kwargs: 附加 pymysql 参数（charset / connect_timeout / read_timeout / write_timeout）
        """
        # 1. 先从环境变量取默认配置
        base = _get_env_conn_config()

        # 2. conn 参数（dict 或 URL）优先级最高，覆盖 base
        if conn is not None:
            if isinstance(conn, str):
                base.update(_parse_conn_url(conn))
            elif isinstance(conn, dict):
                base.update({k: v for k, v in conn.items() if k in _ALLOWED_CONN_KEYS})

        # 3. 构造参数（host/port/user/password/db/database）覆盖
        if host is not None:
            base["host"] = host
        if port is not None:
            base["port"] = int(port)
        if user is not None:
            base["user"] = user
        if password is not None:
            base["password"] = password
        # database 比 db 优先（db 是用户习惯写法）
        if database is not None:
            base["database"] = database
        elif db is not None:
            base["database"] = db

        # 4. 附加 kwargs（charset / connect_timeout 等）
        for k, v in kwargs.items():
            if k in _ALLOWED_CONN_KEYS:
                base[k] = v

        # 保存连接配置到实例
        self.conn_config = base

    def _safe_close(self, conn, cursor=None):
        """主动关闭数据库连接，防止连接池超上限。失败仅记日志，不影响主流程。"""
        try:
            if cursor is not None:
                cursor.close()
        except Exception as e:
            print(f"[db_operate] cursor.close 警告: {e}")
        try:
            conn.close()
        except Exception as e:
            print(f"[db_operate] conn.close 警告: {e}")

    def _fetch(self, sql: str) -> list:
        """执行 SELECT，返回 list[dict]。执行完主动关闭连接。"""
        conn = pymysql.connect(**self.conn_config, cursorclass=DictCursor)
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            return list(cursor.fetchall())
        finally:
            self._safe_close(conn, cursor)

    def _execute(self, sql: str):
        """执行 INSERT/UPDATE/DELETE。执行完主动关闭连接。"""
        conn = pymysql.connect(**self.conn_config)
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            conn.commit()
        finally:
            self._safe_close(conn, cursor)

    def _validate_sql(self, sql, expected_prefix: str) -> str:
        """校验 SQL 类型是否匹配预期，不匹配抛 ValueError。"""
        if not sql or not isinstance(sql, str):
            raise ValueError("SQL 不能为空")
        stripped = sql.strip().rstrip(";")
        if not stripped:
            raise ValueError("SQL 不能为空")
        if not stripped.lower().startswith(expected_prefix.lower()):
            raise ValueError(
                f"SQL 应以 {expected_prefix} 开头，当前: {stripped[:30]}..."
            )
        return stripped

    def query(self, sql, rerun=0, reruntime=1):
        """查询，返回 [{}, {}]。空结果或执行异常返回 []。

        Args:
            sql: SELECT 语句
            rerun: 结果为空时重查次数（int，默认 0 不重查）
            reruntime: 每次重查间隔秒数（int，默认 1）

        注：SQL 校验失败、参数非法、DB 执行异常均视为"查询失败"，统一返回 []。
        """
        try:
            sql = self._validate_sql(sql, "select")

            if not isinstance(rerun, int) or rerun < 0:
                raise ValueError("rerun 应为非负整数")
            if not isinstance(reruntime, int) or reruntime < 0:
                raise ValueError("reruntime 应为非负整数")

            result = self._fetch(sql)
        except Exception as e:
            print(f"[db_operate] query 执行失败: {e}")
            return []

        # 重查机制：结果为空时按 rerun/reruntime 重试
        attempts = 0
        while not result and attempts < rerun:
            time.sleep(reruntime)
            try:
                result = self._fetch(sql)
            except Exception as e:
                print(f"[db_operate] query 第 {attempts + 1} 次重查失败: {e}")
                return []
            attempts += 1

        return result

    def insert(self, sql):
        """新增，成功 True，失败 False。"""
        try:
            sql = self._validate_sql(sql, "insert")
            self._execute(sql)
            return True
        except Exception as e:
            print(f"[db_operate] insert 执行失败: {e}")
            return False

    def update(self, sql):
        """编辑，成功 True，失败 False。"""
        try:
            sql = self._validate_sql(sql, "update")
            self._execute(sql)
            return True
        except Exception as e:
            print(f"[db_operate] update 执行失败: {e}")
            return False

    def delete(self, sql):
        """删除，成功 True，失败 False。"""
        try:
            sql = self._validate_sql(sql, "delete")
            self._execute(sql)
            return True
        except Exception as e:
            print(f"[db_operate] delete 执行失败: {e}")
            return False


# =====================================================================
# 向后兼容：模块级函数（已有代码无需改）
# =====================================================================
def _get_conn_config(conn=None) -> dict:
    """模块级函数用：把 conn 参数合并进环境变量默认配置。"""
    base = _get_env_conn_config()
    if conn is None:
        return base
    if isinstance(conn, str):
        base.update(_parse_conn_url(conn))
    elif isinstance(conn, dict):
        base.update({k: v for k, v in conn.items() if k in _ALLOWED_CONN_KEYS})
    else:
        raise ValueError(f"conn 应为 dict 或 URL 字符串，当前类型: {type(conn).__name__}")
    return base


def query(sql, rerun=0, reruntime=1, conn=None):
    """模块级：查询，返回 [{}, {}]。用法参考 DB.query。"""
    return DB(conn=conn).query(sql, rerun=rerun, reruntime=reruntime)


def insert(sql, conn=None):
    """模块级：新增，成功 True，失败 False。"""
    return DB(conn=conn).insert(sql)


def update(sql, conn=None):
    """模块级：编辑，成功 True，失败 False。"""
    return DB(conn=conn).update(sql)


def delete(sql, conn=None):
    """模块级：删除，成功 True，失败 False。"""
    return DB(conn=conn).delete(sql)


# =====================================================================
# 凭证表集成：通过 system_credentials 表获取数据库连接
# =====================================================================
def get_db_from_credentials(system: str, environment: str):
    """
    从 system_credentials 表获取数据库凭证并创建 DB 连接实例

    Args:
        system: 数据库系统标识（在 system_credentials 表中的 system 字段）
        environment: 环境标识（test/dev/prod 等）

    Returns:
        DB: 数据库连接实例，可直接调用 query/insert/update/delete

    Raises:
        ValueError: 未找到凭证或凭证类型不是 db 时抛出

    使用示例：
        # 获取指定数据库的连接
        db = get_db_from_credentials(system="crm_db", environment="test")

        # 直接执行查询
        rows = db.query("SELECT * FROM users LIMIT 10")

        # 执行增删改
        db.insert("INSERT INTO users(name) VALUES('test')")
        db.update("UPDATE users SET name='updated' WHERE id=1")
        db.delete("DELETE FROM users WHERE id=1")

    注意：
        1. 需要先在 system_credentials 表中配置对应的数据库凭证
        2. type 必须为 'db'
        3. 支持两种连接方式：
           - 方式1: host + port + user + password + db_name
           - 方式2: url (完整的数据库连接字符串)
    """
    from common.credential_helper import get_db_credential

    # 从凭证表获取数据库连接信息
    cred = get_db_credential(system=system, environment=environment)

    if not cred:
        raise ValueError(
            f"未找到数据库凭证: system={system}, environment={environment}。"
            f"请检查 system_credentials 表中是否存在对应记录，且 type='db', is_active=true"
        )

    # 优先使用 URL 连接方式
    if cred.get("url"):
        return DB(conn=cred["url"])

    # 否则使用 host + port + user + password + db_name
    if not all([cred.get("host"), cred.get("user"), cred.get("db_name")]):
        raise ValueError(
            f"数据库凭证不完整: system={system}, environment={environment}。"
            f"必须提供 url 或者 (host + user + db_name)"
        )

    return DB(
        host=cred["host"],
        port=cred.get("port", 3306),
        user=cred["user"],
        password=cred.get("password", ""),
        database=cred["db_name"]
    )
