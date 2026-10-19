#积分2.0校验集
from datetime import datetime
from common.data_check import DataCheck
from common.tec_db import get_db_from_credentials


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
# 获取当月
date =datetime.now().strftime("%Y%-m")
# 收费类型映射
point_type_map = {"Gt01":"FREE",
                  "Gt03":"PAID",}


# 积分派发校验
def points_grant_check(env="test",request_body=None):
    if not request_body:
        raise TypeError("request_body is required")
    expire_at = datetime.fromtimestamp(request_body["expireAt"]).strftime("%Y-%m-%d %H:%M:%S")
    sql =f"""
    select
	*
    from
        point_batch_3 a
    inner join point_grant_record_3 b on
        a.id = b.batch_id
    inner join point_flow_{date}3 c on
        b.flow_id = c.id
    inner join point_flow_detail_{date}3 d on
        c.id = d.flow_id
    where
        a.status = 1
        and
    a.granted_amount = {request_body["amount"]}
        and a.remaining_amount = {request_body["amount"]}
        and 
    a.frozen_amount = 0
        and a.point_type_code = "{request_body["pointTypeCode"]}"
        and a.expire_at = "{expire_at}"
        and b.rule_code = "{request_body["grantRuleCode"]}"
        and a.source_biz_order_id = "{request_body["sourceBizOrderId"]}"
        and c.remark = "{request_body["remark"]}"
        adn c.biz_id = "{request_body["bizId"]}"
    """
    check = point_test1.query(sql=sql)
    if check:
        return True
    else:
        return False


# 积分预扣校验
def points_freeze_check(env="test",request_body=None):
    if not request_body:
        raise TypeError("request_body is required")
    expire_at = datetime.fromtimestamp(request_body["expireAt"]).strftime("%Y-%m-%d %H:%M:%S")
    sql =f"""
    select
	*
    from
        point_batch_3 a
    inner join point_grant_record_3 b on
        a.id = b.batch_id
    inner join point_flow_{date}3 c on
        b.flow_id = c.id
    inner join point_flow_detail_{date}3 d on
        c.id = d.flow_id
    where
        a.status = 1
        and
    a.granted_amount = {request_body["amount"]}
        and a.remaining_amount = {request_body["amount"]}
        and 
    a.frozen_amount = 0
        and a.point_type_code = "{request_body["pointTypeCode"]}"
        and a.expire_at = "{expire_at}"
        and b.rule_code = "{request_body["grantRuleCode"]}"
        and a.source_biz_order_id = "{request_body["sourceBizOrderId"]}"
        and c.remark = "{request_body["remark"]}"
        adn c.biz_id = "{request_body["bizId"]}"
    """
    check = point_test1.query(sql=sql)
    if check:
        return True
    else:
        return False





