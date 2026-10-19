from inspect import FullArgSpec

from points_mall_params import *
from app.modules.code_case.decorators import case
from common.tec_redis import *
from common.data_check import *



# db/redis/job 实例化（惰性初始化，import 阶段失败不报错，避免扫描器/pytest 收集阶段因环境缺失而抛异常）
# 如果当前进程无法连接到 system_credentials / Redis，则对应变量置 None，真正执行用例前请配置好环境
def _try_init():
    _tec_redis = None
    _dc = None
    _job = None

    try:
        _tec_redis = RedisPool()
    except Exception as e:
        print(f"[test_pay_channel] WARN: 初始化 tec_redis 失败，import 继续：{e}")
    try:
        _dc = DataCheck()
    except Exception as e:
        print(f"[test_pay_channel] WARN: 初始化 DataCheck 失败，import 继续：{e}")
    try:
        _job = PowerJobClient(username="ggzhao")
    except Exception as e:
        print(f"[test_pay_channel] WARN: 初始化 PowerJobClient 失败，import 继续：{e}")
    return  _tec_redis, _dc, _job


tec_redis, dc, job = _try_init()


# todo 暂缺具体的落表校验
@case(module="积分2.0", name="积分发放", level="P0",
      description="发放免费和付费积分",case_type="code")
def test_init_points_grant():
    # 获取navos底下的指定积分类型
    point_type_list = get_point_config(sql_name="point_type_list")
    # 获取积分参数
    request_data = get_points_grant_params()
    url = request_data["url"]
    body = request_data["json"]
    headers = request_data["headers"]
    # 统一过期时间
    expire = int(time.time()) + 3600
    # 发起两种积分类型的发放
    for i in point_type_list:
        biz = str(int(time.time() * 1000))
        try:
            # 参数调整
            body["expireAt"] = expire
            body["bizId"] =biz
            body["pointTypeCode"] = i["type_code"]
            print(f"body:{body}")
            res = tec_requests.tec_post(url=url, json=body, header=headers)
            print(res)
            if not res["success"]:
                i["success"] = False,
                i["error"] = res,
            else:
                i["success"] = True
                i["batchId"] = res["data"]["batchId"]
                i["flowId"] = res["data"]["flowId"]
                i["bizId"] = biz
        except Exception as e:
            print(e)
            i["success"] = False,
            i["error"] = str(e)
    # 积分收集器
    points_list = {"grant": point_type_list}
    print(points_list)
    # 暂存redis
    tec_redis.write2(name="points_list",value=points_list,expire=3600)
    # 总断言
    if any("error" in item for item in points_list["grant"]):
        print("存在积分发放失败的用例")
        assert False
    else:
        assert True


@case(module="积分2.0", name="积分预扣", level="P0",
      description="发放免费和付费积分",case_type="code")
def test_init_points_freeze():
    #
    point_list = tec_redis.get_value(name="points_list")
    # 获取积分参数
    request_data = get_points_freeze_params()
    url = request_data["url"]
    body = request_data["json"]
    headers = request_data["headers"]
    # try:
    #     # 参数调整
    #     body["expireAt"] = expire
    #     body["bizId"] =biz
    #     body["pointTypeCode"] = i["type_code"]
    #     print(f"body:{body}")
    #     res = tec_requests.tec_post(url=url, json=body, header=headers)
        # print(res)
        # if not res["success"]:
        #     i["success"] = False,
        #     i["error"] = res,
        # else:
        #     i["success"] = True
        #     i["batchId"] = res["data"]["batchId"]
#             i["flowId"] = res["data"]["flowId"]
#             i["bizId"] = biz
#     except Exception as e:
#         print(e)
#         i["success"] = False,
#         i["error"] = str(e)
# # 积分收集器
# points_list = {"grant": point_type_list}
# print(points_list)
# # 暂存redis
# tec_redis.write2(name="points_list",value=points_list,expire=3600)
#     # 总断言
#     if any("error" in item for item in points_list["grant"]):
#         print("存在积分发放失败的用例")
#         assert False
#     else:
#         assert True







