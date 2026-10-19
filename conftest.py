"""
UI 用例 pytest 配置（pytest 模式配套）

提供 page fixture + 失败截图 hook：

1. page fixture：业务用例声明 ``def test_xxx(page: Page)`` 即可注入 UIBrowser。
   UIBrowser 透明代理 Playwright Page 的全部 API（goto/click/locator/expect...），
   同时可用 ``page.screenshot_to_artifact("step1", step="打开首页")`` 主动留证。

2. 失败截图 hook：用例失败时（call 阶段）自动截图到 QA_ARTIFACT_DIR，
   Playwright TimeoutError 等待元素超时本质是断言类失败，归入 failed 而非 error，
   保证报表口径与 API 用例一致。

注意：@case + @pytest.mark.parametrize 组合被 scanner 检测并记 error，
      一期不支持 1:N 映射展开。
"""
import os

import pytest
from playwright.sync_api import Page

from common.ui_helper import UIBrowser


@pytest.fixture
def page() -> Page:
    """注入 UIBrowser 作为 page fixture。

    业务用例直接用 Playwright Page API，无需关心浏览器启动/关闭：
    ``page.goto()`` / ``page.click()`` / ``expect(locator)...`` 全部可用；
    主动截图用 ``page.screenshot_to_artifact(name, step="描述")``。
    """
    with UIBrowser() as p:
        yield p


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    # hookwrapper 中 yield 返回 pluggy.Result 对象，需 .get_result() 才拿到 TestReport
    outcome = yield
    rep = outcome.get_result()
    # 失败时统一截图（pytest 模式下全局生效，业务用例零侵入）
    if rep.when == "call" and rep.failed:
        page = item.funcargs.get("page")
        if page is not None and os.environ.get("QA_ARTIFACT_DIR"):
            try:
                # 优先走 UIBrowser.screenshot_to_artifact（统一目录/命名/清单登记）；
                # 非 UIBrowser 的原生 page 回退到 Playwright 原生 screenshot
                if hasattr(page, "screenshot_to_artifact"):
                    page.screenshot_to_artifact(
                        item.name, step=f"pytest 失败 hook: {item.name}",
                        category="hook",
                    )
                else:
                    art = os.environ["QA_ARTIFACT_DIR"]
                    os.makedirs(art, exist_ok=True)
                    page.screenshot(path=f"{art}/{item.name}.png", full_page=True)
            except Exception:
                pass
    # 语义归一：等元素超时按断言失败计（failed 而非 error），
    # Playwright TimeoutError 在用例函数内被捕获后改抛 AssertionError 即归入 failed
