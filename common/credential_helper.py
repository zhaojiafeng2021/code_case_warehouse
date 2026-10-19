"""
系统凭证获取工具（独立版，不依赖 qauto-backend）

通过环境变量连接数据库，读取 system_credentials 表。
支持 PostgreSQL（psycopg2）和 MySQL（PyMySQL）。

环境变量优先级（_get_conn 三级回退）：
    1. CRED_DB_*        — 远程 K8s 注入用（sync_repo._inject_cred_env）
    2. DATABASE_URL     — 本地复用 qauto-backend/.env，自动解析
    3. 兜底默认值       — 标准本地 postgres，连不上时会失败

本地独立运行：无需手动配环境变量，自动向上查找并加载 qauto-backend/.env

使用示例：
    from code_testcases.common.credential_helper import get_account_password, get_app_key, get_db_credential

    # 获取账号密码
    result = get_account_password("crm", "test", "admin")
    print(result["password"])

    # 获取密钥
    result = get_app_key("wechat_pay", "test", "wx1234567890")
    print(result["app_secret"])

    # 获取数据库凭证
    result = get_db_credential("mysql_db", "test")
    print(result["host"], result["user"], result["password"])
"""
import os
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urlparse

# 自动向上查找 .env 并加载（本地独立运行用）
# override=False：os.environ 已有的变量优先，不影响远程已注入的 CRED_DB_*
try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(usecwd=True), override=False)
except ImportError:
    pass  # python-dotenv 未安装则跳过（远程容器无 .env 也不影响）

def _get_conn():
    """根据环境变量建立数据库连接（同步）。

    优先级：CRED_DB_* > 解析 DATABASE_URL > 兜底默认值
    每次调用创建一个新连接，调用方负责在 finally 中 close，
    防止连接池超上限。
    """
    # 优先 CRED_DB_*（远程注入）
    db_type = os.environ.get("CRED_DB_TYPE")
    if db_type:
        db_type = db_type.lower()
        host = os.environ.get("CRED_DB_HOST", "localhost")
        port = int(os.environ.get("CRED_DB_PORT", "5432"))
        user = os.environ.get("CRED_DB_USER", "postgres")
        password = os.environ.get("CRED_DB_PASSWORD", "")
        database = os.environ.get("CRED_DB_DATABASE", "qa_platform")
    else:
        # 回退：解析 DATABASE_URL（本地复用 qauto-backend/.env）
        db_url = os.environ.get("DATABASE_URL", "")
        if db_url:
            parsed = urlparse(db_url)
            # scheme: postgresql+asyncpg → postgresql；mysql+pymysql → mysql
            scheme = parsed.scheme or "postgresql"
            db_type = scheme.split("+")[0]
            host = parsed.hostname or "localhost"
            port = parsed.port or (3306 if db_type == "mysql" else 5432)
            user = parsed.username or "postgres"
            password = parsed.password or ""
            # path 形如 /qauto_db，去掉前导斜杠
            database = (parsed.path or "/qa_platform").lstrip("/")
        else:
            # 兜底默认值
            db_type = "postgresql"
            host = "localhost"
            port = 5432
            user = "postgres"
            password = ""
            database = "qa_platform"

    if db_type == "mysql":
        import pymysql
        from pymysql.cursors import DictCursor
        return pymysql.connect(
            host=host, port=port, user=user,
            password=password, database=database,
            charset="utf8mb4",
            cursorclass=DictCursor,
        )
    else:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        return psycopg2.connect(
            host=host, port=port, user=user,
            password=password, dbname=database,
            cursor_factory=RealDictCursor,
        )

def get_credential(
    system: str,
    environment: Optional[str] = None,
    account: Optional[str] = None,
    app_id: Optional[str] = None,
    db_name: Optional[str] = None,
    identifier: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    从 system_credentials 表获取凭证信息

    Args:
        system: 业务系统标识
        environment: 环境标识（可选，不传则不按环境过滤）
        account: 账号（账号密码类型）
        app_id: 应用ID（密钥类型）
        db_name: 数据库名（数据库类型）
        identifier: 通用标识符，自动判断类型（account/app_id/db_name）

    Returns:
        dict: 凭证信息字典，未找到返回 None

    Raises:
        ValueError: 参数不合法时抛出
    """
    if not system:
        raise ValueError("system 参数不能为空")

    # 如果使用 identifier，自动判断填入对应字段
    if identifier:
        if not account and not app_id and not db_name:
            account = identifier
            app_id = identifier
            db_name = identifier

    # 构建查询条件
    conditions = [
        "is_active = true",
        "is_deleted = false",
        f"system = '{system}'"
    ]
    if environment:
        conditions.append(f"environment = '{environment}'")

    if account:
        conditions.append(f"account = '{account}'")
    if app_id:
        conditions.append(f"app_id = '{app_id}'")
    if db_name:
        conditions.append(f"db_name = '{db_name}'")

    where_clause = " AND ".join(conditions)
    sql = f"SELECT * FROM system_credentials WHERE {where_clause} LIMIT 1"

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        print(f"[credential_helper] 查询凭证失败: {e}")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass

def get_account_password(
    system: str,
    environment: Optional[str] = None,
    account: Optional[str] = None
) -> Optional[Dict[str, str]]:
    """
    获取账号密码类型的凭证

    Args:
        system: 业务系统标识
        environment: 环境标识（可选，不传则不按环境过滤）
        account: 账号

    Returns:
        dict: {"account": "xxx", "password": "xxx"}，未找到返回 None
    """
    cred = get_credential(system=system, environment=environment, account=account)
    if cred and cred.get("type") == "account_password":
        return {
            "account": cred.get("account"),
            "password": cred.get("password")
        }
    return None

def get_app_key(
    system: str,
    environment: str,
    app_id: str
) -> Optional[Dict[str, str]]:
    """
    获取密钥类型的凭证

    Args:
        system: 业务系统标识
        environment: 环境标识（可选，不传则不按环境过滤）
        app_id: 应用ID

    Returns:
        dict: {"app_id": "xxx", "app_secret": "xxx"}，未找到返回 None
    """
    cred = get_credential(system=system, environment=environment, app_id=app_id)
    if cred and cred.get("type") == "app_key":
        return {
            "app_id": cred.get("app_id"),
            "app_secret": cred.get("app_secret")
        }
    return None

def get_db_credential(
    system: str,
    environment: str
) -> Optional[Dict[str, Any]]:
    """
    获取数据库连接凭证

    Args:
        system: 业务系统标识（数据库标识）
        environment: 环境标识（可选，不传则不按环境过滤）

    Returns:
        dict: 包含数据库连接信息
            {
                "host": "xxx",
                "port": 3306,
                "user": "xxx",
                "password": "xxx",
                "db_name": "xxx",
                "url": "xxx"  # 如果有
            }
        未找到返回 None
    """
    cred = get_credential(system=system, environment=environment)
    if cred and cred.get("type") == "db":
        result = {
            "host": cred.get("host"),
            "port": cred.get("port", 3306),
            "user": cred.get("account"),  # 数据库用户名复用 account 字段
            "password": cred.get("password"),
            "db_name": cred.get("db_name"),
        }
        if cred.get("url"):
            result["url"] = cred.get("url")
        return result
    return None

if __name__ == "__main__":
    """测试代码"""
    print("=" * 60)
    print("系统凭证获取工具测试")
    print("=" * 60)

    try:
        # 测试账号密码
        print("\n1. 测试获取账号密码:")
        result = get_account_password(system="crm", environment="test", account="admin")
        if result:
            print(f"✓ get_account_password: {result}")
        else:
            print("✗ get_account_password: 未找到")

        # 测试密钥
        print("\n2. 测试获取密钥:")
        result = get_app_key(system="wechat_pay", environment="test", app_id="wx1234567890")
        if result:
            print(f"✓ get_app_key: {result}")
        else:
            print("✗ get_app_key: 未找到")

        # 测试数据库凭证
        print("\n3. 测试获取数据库凭证:")
        result = get_db_credential(system="test_mysql", environment="test")
        if result:
            print(f"✓ get_db_credential: {result}")
        else:
            print("✗ get_db_credential: 未找到")

    except Exception as e:
        print(f"✗ 错误: {str(e)}")

    print("\n" + "=" * 60)