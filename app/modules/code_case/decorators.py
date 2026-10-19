"""
@case 装饰器的兼容 stub（独立用例仓库版本）

作用：在测试平台（qauto-backend）环境中，平台自身的 app.modules.code_case.decorators
      会被优先使用，其 @case 会把用例元信息注册到平台的扫描结果中。
      在独立环境（本仓库 clone 后直接跑 pytest、或在脚本中 import 用例文件）时，
      此 stub 会被加载，@case 装饰器仅保存元信息到函数属性，不会报错，保证用例
      可以被正常 import / pytest 收集和执行。
"""
import functools
from typing import Callable, Any, Optional

# 用例类型：code=接口/脚本, ui=UI自动化, perf=性能(预留，容纳 locust 脚本)
VALID_CASE_TYPES = ("code", "ui", "perf")


def case(
    module: str,
    name: Optional[str] = None,
    level: str = "P2",
    description: Optional[str] = None,
    tags: Optional[list] = None,
    *,
    case_type: str = "code",
    **extra: Any,
) -> Callable:
    """
    通用 @case 装饰器（独立用例仓库 stub 版）

    与 qauto-backend 平台的签名兼容，在本仓库独立运行时：
    - 不报错
    - 把元信息挂到 func.__case__ 上，便于后续脚本扫描读取
    - 原函数照常执行

    Args:
        module: 模块路径，例如 "支付中心-支付渠道-支付宝"
        name: 用例名称，缺省时使用函数名
        level: 优先级 P0/P1/P2/P3，默认 P2
        description: 详细描述
        tags: 标签列表
        case_type: 用例类型（仅关键字传参），取值 code/ui/perf，默认 code
        **extra: 其他扩展字段
    """
    if case_type not in VALID_CASE_TYPES:
        raise ValueError(f"@case 的 case_type 仅支持 {VALID_CASE_TYPES}")

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # 将元信息保存到函数对象上，平台/扫描器可通过 __case__ 读取
        wrapper.__case__ = {
            "module": module,
            "name": name or func.__name__,
            "level": level,
            "description": description or (func.__doc__ or "").strip(),
            "tags": tags or [],
            "case_type": case_type,
            **extra,
        }
        wrapper._case_type = case_type
        return wrapper
    return decorator
