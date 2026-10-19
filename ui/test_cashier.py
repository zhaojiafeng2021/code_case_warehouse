"""
UI 自动化用例示例：收银台渲染检查

演示 @case(case_type="ui") 的两种写法：

1. direct 模式（test_cashier_alipay_render）：用 UIBrowser 上下文管理器，
   函数自包含，无需 pytest fixture。适合简单页面检查。

2. pytest 模式（test_cashier_wechat_render）：用 page fixture（由 conftest
   或本文件内 fixture 提供），复用 pytest 的 setup-teardown / 参数化生态。
   适合复杂场景。

两种写法都通过平台执行入口触发，executor 按 case_type=ui 走 pytest 模式
（--mode pytest），runner 进程内跑 pytest.main()。
"""
from app.modules.code_case.decorators import case
from common.ui_helper import UIBrowser
from playwright.sync_api import Page, expect





@case(module="支付中台-收银台-UI", name="支付宝收银台正常渲染", level="P1",
      project="支付中台", case_type="ui")
def test_example(page: Page) -> None:
    page.goto("https://test01-crm.tec-develop.cn/login")
    page.screenshot_to_artifact("step1_login_page", step="打开登录页")
    page.get_by_text("账密登录").click()
    page.get_by_role("textbox", name="请输入用户名").click()
    page.get_by_role("textbox", name="请输入用户名").fill("chris.ji@tec-do.com")
    page.get_by_role("textbox", name="请输入密码").click()
    page.get_by_role("textbox", name="请输入密码").fill("abc123123")
    page.get_by_role("button", name="登录").click()
    page.screenshot_to_artifact("step2_after_login", step="登录完成")
    page.get_by_text("拜访管理").click()
    page.locator("div:nth-child(5) > .arco-menu-inline-header").click()
    page.get_by_role("menuitem", name="线索列表").click()
    page.screenshot_to_artifact("step3_clue_list", step="进入线索列表")
    page.get_by_role("button", name="创建线索").click()
    page.get_by_role("combobox").filter(has_text="请选择线索来源请选择线索来源").click()
    page.get_by_role("option", name="上下游合作伙伴转介绍").click()
    page.get_by_role("button", name="提交").click()
    expect(page.get_by_role("alert")).to_match_aria_snapshot("- alert: 公司名称、联系人名称、联系方式三选一必填")
    page.get_by_role("textbox", name="公司名称").click()
    page.get_by_role("textbox", name="公司名称").fill("suibian")
    page.get_by_role("button", name="提交").click()
    page.get_by_role("button", name="确定").click()
    expect(page.get_by_role("alert")).to_match_aria_snapshot("- alert: 创建成功")
    page.screenshot_to_artifact("step4_create_success", step="创建线索成功")





