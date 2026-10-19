## 积分2.0代码用例参数
import time
from common.tec_db import get_db_from_credentials
from app.modules.code_case.decorators import case
import ast
from common import tec_requests
from common.tec_powerjob import PowerJobClient


# db 实例化（惰性初始化，import 阶段失败不报错，避免扫描器/pytest 收集阶段因环境缺失而抛异常）
# 如果当前进程无法连接到 system_credentials，则 pay_center_db 置 None，真正执行用例前请配置好环境
# todo 根据环境调用
def _init():
    _db0 = None
    _db1 = None
    try:
        _db0 = get_db_from_credentials(system="point_test0", environment="test")
    except Exception as e:
        print(f"WARN: 初始化 point_test0 失败：{e}")
    try:
        _db1 = get_db_from_credentials(system="point_test1", environment="test")
    except Exception as e:
        print(f"WARN: 初始化 point_test1 失败：{e}")

    return _db0,_db1        # 只在这里 return


# 初始化mysql
point_test0,point_test1 = _init()

# 获取30分钟后的时间戳
expire_time = int(time.time()) + 30 * 60


def get_point_config(env="test",app_id="navos",sql_name=None):
    """根据环境返回积分商城用例入参"""
    env_config = {
        "test":{
        "sqllist":
            {"point_type_list": f"""
                select type_code,type_name,type from point_type_config 
                where JSON_CONTAINS(bind_app_ids, '"{app_id}"')  and status =1 and type_code in("Gt01","Gt03")
                union 
                select type_code,type_name,type from point_type_config 
                where bind_app_ids is Null  and status =1 and type_code in("Gt01","Gt03")
                """
             }}}

    if env not in env_config:
        raise ValueError(f"不支持的环境: {env}, 可选: {list(env_config.keys())}")
    if not sql_name:
        raise ValueError("未入参sql_name")
    data = point_test0.query(env_config[env]["sqllist"]["point_type_list"])
    print(f"sql_name:\n{data}")
    return data



def get_points_grant_params(env="test",app_id="navos",app_secret="123456"):
    """根据环境返回积分商城用例入参"""
    env_config = {
        "test": {
            "url": "https://ltc-point-test01.tec-develop.cn/ltc-point-center/api/v1/points/grant",
            "headers": {"Content-Type": "application/json", "appId": f"{app_id}","appSecret":f"{app_secret}"},
            "json": {
              "effectiveAt": 1,
              "expireAt": None,
              "userId": "123",
              "bizId": None,
              "pointTypeCode": "Gt01",
              "amount": 10000,
              "grantRuleCode": "test grantRuleCode",
              "sourceBizOrderId": "test sourceBizOrderId",
              "remark": "30分钟后过期"
            },
        }
    }
    if env not in env_config:
        raise ValueError(f"不支持的环境: {env}, 可选: {list(env_config.keys())}")

    conf = env_config[env]
    return {
        "url": conf["url"],
        "json": conf["json"],       # POST body,按用例覆盖
        "params": None,     # 查询参数,按用例覆盖
        "headers": conf["headers"],
        "sqllist": [
        ],
    }


def get_points_deduct_params(env="test",app_id="navos",app_secret="123456"):
    """根据环境返回积分商城用例入参"""
    env_config = {
        "test": {
            "url": "https://ltc-point-test01.tec-develop.cn/ltc-point-center/api/v1/points/deduct",
            "headers": {"Content-Type": "application/json", "appId": f"{app_id}","appSecret":f"{app_secret}"},
            "json": {
                  "userId": "123",
                  "bizId": None,
                  "sceneCode": "LLM",
                  "amount": 10000,
                  "sessionId": "test sessionId",
                  "modelCallId": "test modelCallId",
                  "remark": "test deduct",
                  "allowedPointTypeCodes": ["Gt01","Gt03"],
                  "excludedPointTypeCodes": []
                },
        }
    }
    if env not in env_config:
        raise ValueError(f"不支持的环境: {env}, 可选: {list(env_config.keys())}")

    conf = env_config[env]
    return {
        "url": conf["url"],
        "json": conf["json"],       # POST body,按用例覆盖
        "params": None,     # 查询参数,按用例覆盖
        "headers": conf["headers"],
        "sqllist": [
        ],
    }


def get_points_return_params(env="test",app_id="navos",app_secret="123456"):
    """根据环境返回积分商城用例入参"""
    env_config = {
        "test": {
            "url": "https://ltc-point-test01.tec-develop.cn/ltc-point-center/api/v1/points/return",
            "headers": {"Content-Type": "application/json", "appId": f"{app_id}","appSecret":f"{app_secret}"},
            "json": {
              "userId": "123",
              "bizId": None,
              "sessionId": "test sessionId",
              "originalBizId": "test originalBizId",
              "amount": 9000,
              "reason": "test return",
            },
        }
    }
    if env not in env_config:
        raise ValueError(f"不支持的环境: {env}, 可选: {list(env_config.keys())}")

    conf = env_config[env]
    return {
        "url": conf["url"],
        "json": conf["json"],       # POST body,按用例覆盖
        "params": None,     # 查询参数,按用例覆盖
        "headers": conf["headers"],
        "sqllist": [
        ],
    }


def get_points_freeze_params(env="test",app_id="navos",app_secret="123456"):
    """根据环境返回积分商城用例入参"""
    env_config = {
        "test": {
            "url": "https://ltc-point-test01.tec-develop.cn/ltc-point-center/api/v1/points/freeze",
            "headers": {"Content-Type": "application/json", "appId": f"{app_id}","appSecret":f"{app_secret}"},
            "json": {
          "userId": "123",
          "bizId": None,
          "sceneCode": "LLM",
          "amount": 2000,
          "remark": "test freeze",
          "allowedPointTypeCodes": ["Gt01","Gt03"],
          "excludedPointTypeCodes": []
        },
        }
    }
    if env not in env_config:
        raise ValueError(f"不支持的环境: {env}, 可选: {list(env_config.keys())}")

    conf = env_config[env]
    return {
        "url": conf["url"],
        "json": conf["json"],       # POST body,按用例覆盖
        "params": None,     # 查询参数,按用例覆盖
        "headers": conf["headers"],
        "sqllist": [
        ],
    }


def get_points_confirm_params(env="test",app_id="navos",app_secret="123456"):
    """根据环境返回积分商城用例入参"""
    env_config = {
        "test": {
            "url": "https://ltc-point-test01.tec-develop.cn/ltc-point-center/api/v1/points/confirm",
            "headers": {"Content-Type": "application/json", "appId": f"{app_id}","appSecret":f"{app_secret}"},
            "json":{
      "userId": "123",
      "bizId": None,
      "originalBizId": None
    }
            }
    }
    if env not in env_config:
        raise ValueError(f"不支持的环境: {env}, 可选: {list(env_config.keys())}")

    conf = env_config[env]
    return {
        "url": conf["url"],
        "json": conf["json"],       # POST body,按用例覆盖
        "params": None,     # 查询参数,按用例覆盖
        "headers": conf["headers"],
        "sqllist": [
        ],
    }

def get_points_unfreeze_params(env="test",app_id="navos",app_secret="123456"):
    """根据环境返回积分商城用例入参"""
    env_config = {
        "test": {
            "url": "https://ltc-point-test01.tec-develop.cn/ltc-point-center/api/v1/points/unfreeze",
            "headers": {"Content-Type": "application/json", "appId": f"{app_id}","appSecret":f"{app_secret}"},
            "json":{
      "userId": "123",
      "bizId": None,
      "originalBizId": None
    }
            }
    }
    if env not in env_config:
        raise ValueError(f"不支持的环境: {env}, 可选: {list(env_config.keys())}")

    conf = env_config[env]
    return {
        "url": conf["url"],
        "json": conf["json"],       # POST body,按用例覆盖
        "params": None,     # 查询参数,按用例覆盖
        "headers": conf["headers"],
        "sqllist": [
        ],
    }


def get_points_detail_params(env="test",app_id="navos",app_secret="123456"):
    """根据环境返回积分商城用例入参"""
    env_config = {
        "test": {
            "url": "https://ltc-point-test01.tec-develop.cn/ltc-point-center/api/v1/points/balance/query",
            "headers": {"Content-Type": "application/json", "appId": f"{app_id}","appSecret":f"{app_secret}"},
            "json":{
              "userId": "123",
              "allowedPointTypeCodes":["Gt01","Gt03"],
              "excludedPointTypeCodes":[],
              "includeDetails": True,
              "cursor":"",
              "limit":100
            }
            }
    }
    if env not in env_config:
        raise ValueError(f"不支持的环境: {env}, 可选: {list(env_config.keys())}")

    conf = env_config[env]
    return {
        "url": conf["url"],
        "json": conf["json"],       # POST body,按用例覆盖
        "params": None,     # 查询参数,按用例覆盖
        "headers": conf["headers"],
        "sqllist": [
        ],
    }


# 获取汇总和批次的核心字段
def get_user_points_from_api(env="test",
                             app_id="navos",
                             app_secret="123456",
                             user_id ="123",
                             batch_ids =None):
    request_data = get_points_detail_params()
    body = request_data["json"]
    header = request_data["headers"]
    url = request_data["url"]
    res = tec_requests.tec_post(url=url,json=body,header=header)
    res1 = res.copy()
    print(res1)
    if batch_ids is not None:
        details1 = []
        for i in res1["data"]["details"]:
            if i["batchId"] in batch_ids:
                details1.append(i)
    del res1["data"]["details"]
    print(f"获取到用户积分汇总和指定批次数据：\n{res1}")
    return res1


