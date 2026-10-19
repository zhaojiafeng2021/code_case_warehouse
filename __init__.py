"""
代码用例根目录

在本地分支的此目录下编写代码用例，合并到 master 后由平台「扫描代码」入库。

用法：
    from app.modules.code_case.decorators import case

    @case(module="支付中心-支付渠道-支付宝", name="支付宝下单成功", level="P0",
          description="验证支付宝渠道正常下单")
    def test_alipay_order():
        assert True

module 参数必传，用 "-" 分隔层级；扫描时不存在的层级会自动逐级创建。
子目录可自由组织（按业务线分目录），扫描器会递归查找所有 .py 文件。
"""
