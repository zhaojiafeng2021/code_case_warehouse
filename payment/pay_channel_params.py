# 支付渠道参数获取
from common.tec_db import get_db_from_credentials


# db 实例化（惰性初始化，import 阶段失败不报错，避免扫描器/pytest 收集阶段因环境缺失而抛异常）
# 如果当前进程无法连接到 system_credentials，则 pay_center_db 置 None，真正执行用例前请配置好环境
def _init():
    _db = _redis = _dc = None
    try:
        _db = get_db_from_credentials(system="pay_center", environment="test01")
    except Exception as e:
        print(f"WARN: 初始化 pay_center_db 失败：{e}")
    return _db  # 只在这里 return


# 初始化mysql、redis、dc
pay_center_db = _init()


# 获取项目底下的可用支付渠道
def get_pay_channel_list(env="test01",app_id="UA",):
    # 获取数据库appId=XX底下的可用渠道
    env_config = {
        "test01": {
                "get_channel_list" : f"""
                      select a.id, a.channel_code, b.support_currencies
                      from pay_channel_merchant_config a
                               inner join pay_channel b on a.channel_code = b.channel_code
                               inner join pay_channel_merchant_app_relation c on c.channel_merchant_config_id = a.id
                      where c.app_id in ('{app_id}')
                        and a.status = 1
                        and b.status = 1
                        and c.status = 1
                      order by a.id \
                      """}}
    if env not in env_config:
        raise ValueError(f"不支持的环境: {env}, 可选: {list(env_config.keys())}")
    conf = env_config[env]
    res1 = pay_center_db.query(sql=conf["get_channel_list"])
    print(f"获取当前{app_id}底下可用的渠道：{res1}")
    return res1


def get_order_calling_params(env="test01", app_id="UA", app_secret="UA"):
    """根据环境返回积分商城用例入参"""
    env_config = {
        "test01": {
            "headers": {
                "appId": app_id,
                "appSecret": app_secret,
            },
            "json": {
                "userId": "ggtest2026",
                "merchantId": 11,
                "bizOrderNo": "ggtest2026",
                "transactionNo": "",
                "bizType": "RECHARGE",
                "subject": "ggtestsubject",
                "paymentAmount": 120,
                "paymentCurrency": None,
                "payableCurrency": "USD",
                "payableAmount": 100,
                "expireSeconds": 900,
                "channelExpireSeconds": 900,
                "extraInfo": "extraInfo test",
                "channelCode": "STRIPE",
                "payScene": "",
                "notifyUrl": "http://ggtestnotifyUrl.com"
            },
            "url": "https://test01-ltc-pay.tec-develop.cn/ltc-pay-center/api/v1/pay/payment"
        }
    }
    if env not in env_config:
        raise ValueError(f"不支持的环境: {env}, 可选: {list(env_config.keys())}")

    conf = env_config[env]
    return {
        "url": conf["url"],
        "json": conf["json"],  # POST body,按用例覆盖
        "params": None,  # 查询参数,按用例覆盖
        "headers": conf["headers"],
        "sqllist": [
        ],
    }


def get_order_detail_params(env="test01", app_id="UA", app_secret="UA"):
    """根据环境返回积分商城用例入参"""
    env_config = {
        "test01": {
            "headers": {
                "appId": app_id,
                "appSecret": app_secret,
            },
            "json": {
            },
            "url": "https://test01-ltc-pay.tec-develop.cn/ltc-pay-center/api/v1/pay/query",
            "sqllist": {"get_plan_b_order":f"""
        select channel_code,biz_order_no as bizOrderNo,transaction_no as transactionNo  
        from pay_order_15 order by id desc limit 1
        """}
        }
    }
    if env not in env_config:
        raise ValueError(f"不支持的环境: {env}, 可选: {list(env_config.keys())}")

    conf = env_config[env]
    return {
        "url": conf["url"],
        "json": conf["json"],  # POST body,按用例覆盖
        "params": None,  # 查询参数,按用例覆盖
        "headers": conf["headers"],
        "sqllist": conf["sqllist"]
    }
