from common.tec_redis import *
from common.data_check import DataCheck
from common.tec_db import get_db_from_credentials
from decimal import *


# db 实例化（惰性初始化，import 阶段失败不报错，避免扫描器/pytest 收集阶段因环境缺失而抛异常）
# 如果当前进程无法连接到 system_credentials，则 pay_center_db 置 None，真正执行用例前请配置好环境
def _init():
    _db = _redis = _dc = None
    try:
        _db = get_db_from_credentials(system="pay_center", environment="test01")
    except Exception as e:
        print(f"WARN: 初始化 pay_center_db 失败：{e}")
    try:
        _redis = RedisPool()
    except Exception as e:
        print(f"WARN: 初始化 tec_redis 失败：{e}")
    try:
        _dc = DataCheck()
    except Exception as e:
        print(f"WARN: 初始化 DataCheck 失败：{e}")
    return _db, _redis, _dc          # 只在这里 return

# 初始化mysql、redis、dc
pay_center_db,tec_redis,dc = _init()


# 获取项目底下的可用支付渠道
# def get_pay_channel_list(env="test01",app_id="UA",):
#     # 获取数据库appId=XX底下的可用渠道
#     sql = f"""
#           select a.id, a.channel_code, b.support_currencies
#           from pay_channel_merchant_config a
#                    inner join pay_channel b on a.channel_code = b.channel_code
#                    inner join pay_channel_merchant_app_relation c on c.channel_merchant_config_id = a.id
#           where c.app_id in ('{app_id}')
#             and a.status = 1
#             and b.status = 1
#             and c.status = 1
#           order by a.id \
#           """
#     res1 = pay_center_db.query(sql=sql)
#     print(f"获取当前{app_id}底下可用的渠道：{res1}")
#     return res1


#渠道订单落表校验
def pay_order_into_db_check(respond_body,expect):
    # 确认分表
    num = str(int(respond_body['data']["transactionNo"][-3:]) % 32)
    sql2 = f"""
               select a.channel_code as channelCode  ,a.user_id as userId , a.channel_merchant_id as merchantId,
               a.biz_order_no as bizOrderNo ,b.biz_type as bizType ,b.subject  ,b.extra_info as extraInfo, a.status,
               a.pay_scene as payScene ,b.notify_url as notifyUrl, a.expire_time as channelExpireSeconds, b.expire_time as expireSeconds,
               a.payable_currency as payableCurrency,a.payable_amount as payableAmount,a.payment_currency as paymentCurrency,
               a.payment_amount as paymentAmount, a.exchange_rate 
               from pay_order_{num} a
               inner join pay_transaction_{num} b on a.biz_order_no =b.biz_order_no
               where a.pay_order_no ="{respond_body["data"]["payOrderNo"]}"
                       """
    # print(sql2)
    # 请求参数与数据库对比
    db_data = pay_center_db.query(sql=sql2, rerun=2)[0]
    print(f"支付渠道订单落表校验\ndb_data:{db_data}\nexpect :{expect}")
    check = DataCheck().compare_dicts(db_data,expect,datetime_tolerance_ms=15000,
                                                          ignore_fields=["transactionNo"])
    return check


# 订单详情校验
def pay_order_detail_check(tra_no,api_data):
    num = str(int(tra_no[-3:]) % 32)
    sql = f"""
            select a.channel_code ,a.transaction_no as transactionNo ,a.user_id as userId ,
            a.biz_order_no as bizOrderNo ,b.biz_type as bizType ,b.subject ,b.payable_amount as payableAmount ,
            b.payable_currency as payableCurrency,b.status ,b.expire_time as expireTime ,
            b.extra_info as extraInfo,a.channel_order_no as channelOrderNo, 
            a.estimated_channel_received_amount as estimatedReceivedAmount,a.pay_order_no as payOrderNo
            from pay_order_{num} a
            inner join pay_transaction_{num} b on a.biz_order_no =b.biz_order_no
            where a.transaction_no  ="{tra_no}"
            """
    print(sql)
    db_data = pay_center_db.query(sql=sql)[0]
    print(f"支付渠道订单详情校验\ndb_data:{db_data}\n api_data:{api_data}")
    diff = DataCheck().compare_dicts(api_data, db_data, ignore_fields=["channel_code", "receivableCurrency"])
    print(diff)
    return diff


# 渠道订单通用计费规则校验
def fee_check(tra_no):
    """
    计费规则校验函数

    Args:
        tra_no: 交易单号

    Returns:
        dict: 包含计费相关字段的字典
    """
    # 确认分表
    num = str(int(tra_no[-3:]) % 32)
    sql1 = f"""
    select c.id,c.fee_rule_type ,c.fee_value ,c.fee_tier_json,c.platform_fee_rate ,c.fee_type 
    from pay_transaction_{num} a
    inner join pay_order_{num} b
    on a.transaction_no =b.transaction_no
    inner join  pay_channel_merchant_fee_rule c
    on b.channel_merchant_id =c.channel_merchant_config_id
    where a.transaction_no in("{tra_no}")
    and c.status =1 
    """
    sql2 =f"""
    select a.payment_amount,a.channel_payment_amount ,
    a.platform_fee ,a.estimated_channel_fee ,a.estimated_channel_received_amount ,a.channel_fee_rule_id ,
    a.channel_fee_type,a.channel_fee_rule_type ,a.channel_fee_value ,a.platform_fee_rate
    from pay_order_{num} a where a.transaction_no IN("{tra_no}")
    """
    # 获取计费规则 和订单费用
    fee_rule_info = pay_center_db.query(sql=sql1)
    order_fee_info = pay_center_db.query(sql=sql2)[0]
    payment_amount = order_fee_info["payment_amount"]
    # 预期初始化
    expect = {}
    # 场景1: fee_rule_info 为 None 或空，使用默认赋值
    if not fee_rule_info or fee_rule_info is None:
        expect = {
            'channel_payment_amount': float(payment_amount),
            'estimated_channel_fee': float(Decimal('0')),
            'estimated_channel_received_amount': float(payment_amount),
            'platform_fee': float(Decimal('0')),
            'channel_fee_type': "NONE",  #不规范
            'channel_fee_rule_type': "NONE",
            'channel_fee_value': float(Decimal('0')),
            'platform_fee_rate': float(Decimal('0')),
            'channel_fee_rule_id': None
        }
    else:
        # 场景2: fee_rule_info 有值，正常计算
        fee_rule_info = fee_rule_info[0]
        # 1. 计算平台费用
        platform_fee_rate = fee_rule_info.get('platform_fee_rate', Decimal('0'))
        platform_fee = payment_amount * platform_fee_rate

        # 2. 获取渠道费用配置
        fee_value = fee_rule_info.get('fee_value')
        fee_tier_json = fee_rule_info.get('fee_tier_json')
        fee_rule_type = fee_rule_info.get('fee_rule_type')
        fee_type = fee_rule_info.get('fee_type')
        channel_fee_rule_id = fee_rule_info.get('id')

        # 3. 计算渠道费用
        channel_fee_value = None
        estimated_channel_fee = Decimal('0')

        # 3.1 如果 fee_value 有值且 fee_rule_type = PERCENTAGE
        if fee_value is not None and fee_rule_type == 'PERCENTAGE':
            channel_fee_value = fee_value
            estimated_channel_fee = payment_amount * Decimal(str(fee_value))

        # 3.2 如果 fee_tier_json 有值，需要解析阶梯费率
        elif fee_tier_json:
            import json
            if isinstance(fee_tier_json, str):
                tier_list = json.loads(fee_tier_json)
            else:
                tier_list = fee_tier_json

            # 判断 payment_amount 在哪个区间
            for tier in tier_list:
                min_amount = Decimal(str(tier['minAmount']))
                max_amount = Decimal(str(tier['maxAmount'])) if tier['maxAmount'] is not None else None

                # 判断金额是否在当前区间 [minAmount, maxAmount)
                if max_amount is None:
                    # 最后一个区间，无上限
                    if payment_amount >= min_amount:
                        channel_fee_value = Decimal(str(tier['feeValue']))
                        break
                else:
                    # 前面的区间，左闭右开
                    if min_amount <= payment_amount < max_amount:
                        channel_fee_value = Decimal(str(tier['feeValue']))
                        break

            # 根据 fee_rule_type 计算费用
            if fee_rule_type == 'TIERED_PERCENTAGE':
                estimated_channel_fee = payment_amount * channel_fee_value
            elif fee_rule_type == 'TIERED_FIXED':
                estimated_channel_fee = channel_fee_value

        # 4. 根据 fee_type 计算最终金额
        if fee_type == 'OUTER_CAL':
            # 外扣：渠道支付金额 = 订单金额 + 渠道费用，实收金额 = 订单金额
            channel_payment_amount = payment_amount + estimated_channel_fee
            estimated_channel_received_amount = payment_amount
        elif fee_type == 'INNER':
            # 内扣：渠道支付金额 = 订单金额，实收金额 = 订单金额 - 渠道费用
            channel_payment_amount = payment_amount
            estimated_channel_received_amount = payment_amount - estimated_channel_fee
        else:
            # 默认情况
            channel_payment_amount = payment_amount
            estimated_channel_received_amount = payment_amount

        # 5. 组装返回结果
        expect = {
            'channel_payment_amount': float(channel_payment_amount),
            'estimated_channel_fee': float(estimated_channel_fee),
            'estimated_channel_received_amount': float(estimated_channel_received_amount),
            'platform_fee': float(platform_fee),
            'channel_fee_type': fee_type,
            'channel_fee_rule_type': fee_rule_type,
            'channel_fee_value': float(channel_fee_value) if channel_fee_value is not None else None,
            'platform_fee_rate': float(platform_fee_rate),
            'channel_fee_rule_id': channel_fee_rule_id
        }

    # 6. 预期与落表的比对
    print(F"支付渠道订单计费校验\nexpect: {expect}\n ,db:{order_fee_info}")
    diff = DataCheck().compare_dicts(order_fee_info,expect,ignore_fields=['payment_amount'])
    # print(F"diff: {diff}")
    return diff


