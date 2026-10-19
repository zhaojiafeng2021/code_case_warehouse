from datetime import datetime, timedelta, timezone
from app.modules.code_case.decorators import case
import ast
from common import tec_requests
from common.tec_powerjob import PowerJobClient
from pay_channel_check import *
from pay_channel_params import *


# db/redis/job 实例化（惰性初始化，import 阶段失败不报错，避免扫描器/pytest 收集阶段因环境缺失而抛异常）
# 如果当前进程无法连接到 system_credentials / Redis，则对应变量置 None，真正执行用例前请配置好环境
def _try_init():
    _pay_center_db = None
    _tec_redis = None
    _dc = None
    _job = None
    try:
        _pay_center_db = get_db_from_credentials(system="pay_center", environment="test01")
    except Exception as e:
        print(f"[test_pay_channel] WARN: 初始化 pay_center_db 失败，import 继续：{e}")
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
    return _pay_center_db, _tec_redis, _dc, _job


pay_center_db, tec_redis, dc, job = _try_init()


@case(module="支付中心-支付渠道", name="支付渠道调用", level="P0",
      description="验证UA各渠道正常下单并返回支付链接",project="支付中台")
def test_pay_channel_call_success():
    # 避免短时间重测阻塞
    check1 = tec_redis.get_value(name="pending_orders_failed")
    if check1:
        tec_redis.write2(name="pending_orders_failed",value=None)
    # 获取接口参数
    request_data = get_order_calling_params()
    header = request_data["headers"]
    body = request_data["json"]
    url = request_data["url"]
    # 获取数据库appId=UA底下的可用渠道
    res1 = get_pay_channel_list()
    for i in res1:
        # 初始化支付订单参数
        pending_order = {
            "channel_code": i["channel_code"],
            "bizOrderNo": body["bizOrderNo"],
        }
        try:
            # 请求参数组装
            print(f"执行用例参数：{i}", type(i))
            body["channelCode"] = i["channel_code"]
            body["merchantId"] = i["id"]
            body["paymentCurrency"] = ast.literal_eval(i['support_currencies'])[0]
            body["bizOrderNo"] = str(int(time.time() * 1000))
            body["expireSeconds"] = 900
            body["channelExpireSeconds"] = 900
            print(f"url:{url}\nheader:{header}\nbody:{body}")
            res3 = tec_requests.tec_post(url=url, json=body, header=header)
            # print(F"body:{body},header:{header}")
            print(res3)
            # 预期组装
            # 固定按 UTC+8 取当前时间（远程容器时区为 UTC，datetime.now() 会与 DB 北京时间差 8 小时）
            expect_expire =(datetime.now(timezone(timedelta(hours=8)))+timedelta(seconds=900)).strftime("%Y-%m-%d %H:%M:%S")
            expect = body.copy()
            expect["channelExpireSeconds"] =expect_expire
            expect["expireSeconds"] =expect_expire
            expect["status"] = "CHANNEL_PROCESSING"
            expect["exchange_rate"] = Decimal('1.2')
            # 如果paymentCurrency为null或者payableCurrency=paymentCurrency
            if expect["payableCurrency"] == expect["paymentCurrency"] or expect["paymentCurrency"] is None:
                expect["paymentAmount"] =expect["payableAmount"]
                expect["paymentCurrency"] = expect["payableCurrency"]
                expect["exchange_rate"] = Decimal('1')
            # 特殊处理
            if expect["channelCode"] == "CHINAPNR" :
                expect["extraInfo"] = None
            # API初步断言
            if "code" in res3.keys():
                if res3["success"] :
                    if res3["data"]["status"] == "PENDING" and res3["data"]["payUrl"] is not None:
                        pending_order["transactionNo"] = res3["data"]["transactionNo"]
                        # 检查订单信息落表
                        check =pay_order_into_db_check(respond_body=res3,expect=expect)
                        if check:
                            # 落表校验失败
                            pending_order["error"] = "落表校验失败，具体查看比对结果"
                            print(f"{res3["data"]["transactionNo"]}落表校验失败\n{check}")
                            tec_redis.write(name="pending_orders_failed", value=pending_order, expire=6000)
                        else:
                            # 核对计费落表
                            check = fee_check(tra_no=res3["data"]["transactionNo"])
                            if check:
                                print(f"{res3["data"]["transactionNo"]}计费校验失败\n{check}")
                                pending_order["error"] = str(check)
                                tec_redis.write(name="pending_orders_failed", value=pending_order, expire=6000)
                            else:
                                tec_redis.write(name="pending_orders", value=pending_order, expire=3000)
                else:
                    if "message" in res3.keys():
                        pending_order["error"] = res3["msg"]
                    else:
                        pending_order["error"] = res3
                    tec_redis.write(name="pending_orders_failed", value=pending_order, expire=6000)
            # 记录失败的渠道订单
            else:
                pending_order["error"] = str(res3) if not isinstance(res3, str) else res3
                tec_redis.write(name="pending_orders_failed", value=pending_order, expire=6000)
        # 其他异常捕捉
        except Exception as error:
            pending_order["error"] = str(error)
            tec_redis.write(name="pending_orders_failed", value=pending_order, expire=6000)
            print(error)
    # 获取失败列表
    failed_list = tec_redis.get_value(name="pending_orders_failed")
    print(failed_list)
    if failed_list:
        print(f"存在失败的订单渠道：{failed_list}")
        assert False
    else:
        assert True




@case(module="支付中心-支付渠道", name="渠道订单查询", level="P0",
      description="订单查询",project="支付中台")
def test_pay_channel_order_detail():
    # 获取pending order列表
    pending_orders = tec_redis.get_value(name="pending_orders")
    print("pending_orders:", pending_orders,type(pending_orders))
    # 获取接口参数
    request_data =get_order_detail_params()
    url = request_data["url"]
    header = request_data["headers"]
    body = request_data["json"]
    # 兜底
    if not pending_orders:
        print("获取不到pending订单数据，兜底取数据库订单数据")
        sql = request_data["sqllist"]["get_plan_b_order"]
        print(sql)
        pending_orders = pay_center_db.query(sql=sql)
        print("pending_orders:", pending_orders,type(pending_orders))
        if not pending_orders:
            print("兜底取不到订单数据")
            assert False
    # 初始化测试失败集合
    failed_list = []
    print("pending_orders:", pending_orders,type(pending_orders))
    # 参数组装
    for i in pending_orders:
        body["transactionNo"] = i["transactionNo"]
        body["bizOrderNo"] = i["bizOrderNo"]
        res = tec_requests.tec_post(url=url, json=body, header=header)
        # 初始化测试失败集合
        failed_list = []
        if res["code"] == "200":
            # 订单详情字段校验
            api_data = res["data"]
            check = pay_order_detail_check(api_data=api_data,tra_no=i["transactionNo"])
            if check:
                print(F"diff_result:{check}")
                failed_list.append({"channel_code":i["channel_code"],"bizOrderNo":i["bizOrderNo"],
                                    "error":"数据校验失败，请查看数据比对情况"})
        else:
            failed_list.append({"channel_code": i["channel_code"], "bizOrderNo": i["bizOrderNo"],
                                "error": "接口调用失败，请查看接口调用情况"})
            assert False
    if failed_list:
          print("存在订单查询失败的渠道，请排查")
          assert False
    else:
        assert True


# @case(module="支付中心-支付渠道", name="订单超时闭环", level="P0",
#       description="最好在订单发起半小时后执行")
# def test_pay_channel_order_close():
#     # 获取pending order 列表并移除
#     pending_orders = json.loads(tec_redis.get_value(name="pending_orders"))
#     print("pending_orders:", pending_orders,type(pending_orders))
#     wait_update_order_list = str(tuple(item['transactionNo'] for item in pending_orders))
#     print("wait_update_order_list:", wait_update_order_list)
#     # 确认分表
#     num = str(int(pending_orders[0]["transactionNo"][-3:])% 32)
#     #获取当前时间
#     current_times = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
#     print("current_times", current_times,type(current_times))
#     # 更新订单过期时间
#     sql = f"""update pay_order_{num} set expire_time ='{current_times}' where
#     transaction_no in {wait_update_order_list}"""
#     print(sql)
#     update = pay_center_db.update(sql=sql)
#     print(update)
#     if update:
#             # 执行定时任务
#             res = job.get(path="/job/run?jobId=30&appId=5")
#             print(res, type(res))
            # if res["success"]:
