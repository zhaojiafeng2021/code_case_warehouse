"""
UI 自动化浏览器封装（Playwright）

提供 UIBrowser 上下文管理器：进入返回 page，退出自动清理浏览器资源。
失败时自动截图到 QA_ARTIFACT_DIR（由 executor 注入的环境变量）。

设计要点：
- --no-sandbox / --disable-dev-shm-usage：容器内 /dev/shm 仅 64MB，Chromium 会崩；
  第一期用启动参数绕开，零部署改动（后续可挂 emptyDir(Memory) 到 /dev/shm）
- headless=True：CI/容器场景无显示器
- viewport 固定 1280x720：截图一致性
- trace 按需开启（QA_UI_TRACE=1），默认关，单文件几 MB~几十 MB
- 截图清单 manifest.json：每次截图（主动/失败/hook）都记一条元信息，
  executor 读取后合并进 artifacts，前端按 category 分组 + order 时间线展示
"""
import json
import os
import re
import time

from playwright.sync_api import sync_playwright

# 容器内运行 Chromium 的必要参数
LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]

# 清单文件名（executor 读取后合并进 artifacts 字段）
MANIFEST_FILENAME = "manifest.json"


class UIBrowser:
    """上下文管理器：进入返回 page，退出自动清理；异常自动截图到 QA_ARTIFACT_DIR。

    用法（direct 模式）::

        with UIBrowser() as page:
            page.goto("https://example.com")
            page.wait_for_selector(".btn", timeout=10000)
            assert page.locator(".title").inner_text() == "Hello"

    用法（pytest 模式，作为 fixture 注入）::

        @pytest.fixture
        def page():
            with UIBrowser() as page:
                yield page

    主动截图（成功步骤也可留证）::

        with UIBrowser() as page:
            page.goto("https://example.com")
            page.screenshot_to_artifact("step1_home", step="打开首页")
            page.click(".btn")
            page.screenshot_to_artifact("step2_after_click", step="点击按钮后")
    """

    def __enter__(self):
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=True, args=LAUNCH_ARGS)
        # trace 按需开启（executor 注入 QA_UI_TRACE=1）
        self._tracing = os.environ.get("QA_UI_TRACE") == "1"
        if self._tracing:
            self.browser.start_tracing()
        self.page = self.browser.new_page(viewport={"width": 1280, "height": 720})
        # 截图清单：每条 {name, category, step, order, timestamp}
        self._artifacts_meta: list[dict] = []
        self._shot_seq = 0
        return self

    def __getattr__(self, name):
        """透明代理 Playwright Page 的属性/方法（goto/click/locator/screenshot...）。

        __getattr__ 仅在常规查找失败时触发；screenshot_to_artifact 等本类方法
        不会走到这里。__enter__ 之前 page 未初始化时直接抛 AttributeError。
        """
        page = self.__dict__.get("page")
        if page is None:
            raise AttributeError(name)
        return getattr(page, name)

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is not None:
                self._dump_artifacts()
        finally:
            try:
                if self._tracing:
                    self._dump_trace()
            except Exception:
                pass
            # 无论成功失败，都把清单落盘（executor 读取后合并进 artifacts）
            self._write_manifest()
            try:
                self.browser.close()
            except Exception:
                pass
            try:
                self._pw.stop()
            except Exception:
                pass
        return False

    def screenshot_to_artifact(
        self,
        name: str = "",
        step: str = "",
        category: str = "step",
        full_page: bool = True,
    ):
        """主动截图到 QA_ARTIFACT_DIR（成功步骤也可留证，不依赖失败自动截图）。

        截图会随执行产物一起上传 MinIO，前端执行详情里可按分类预览。

        Args:
            name: 截图名（不含扩展名），如 "step1_home"；留空用时间戳
            step: 步骤描述（前端展示用，如 "打开首页"）；留空回退用 name
            category: 截图分类，step=步骤截图, failure=失败自动截图,
                      hook=pytest 失败 hook 截图
            full_page: 是否整页长截图，默认 True

        Returns:
            截图文件绝对路径；QA_ARTIFACT_DIR 未设置（本地非 executor 环境）时返回 None
        """
        art_dir = os.environ.get("QA_ARTIFACT_DIR")
        if not art_dir:
            return None
        os.makedirs(art_dir, exist_ok=True)
        # 文件名清洗：只保留字母数字- _，其余替换为 _，防路径穿越
        label = re.sub(r"[^A-Za-z0-9_-]", "_", name).strip("_") if name else ""
        if not label:
            label = f"shot_{int(time.time() * 1000)}"
        # 避免同名覆盖（同一用例多张同名截图）
        filename = f"{label}.png"
        path = os.path.join(art_dir, filename)
        if os.path.exists(path):
            filename = f"{label}_{int(time.time() * 1000)}.png"
            path = os.path.join(art_dir, filename)
        try:
            self.page.screenshot(path=path, full_page=full_page)
        except Exception:
            return None
        # 登记到内存清单
        self._shot_seq += 1
        self._artifacts_meta.append({
            "name": filename,
            "category": category,
            "step": step or name or label,
            "order": self._shot_seq,
            "timestamp": time.time(),
        })
        return path

    def _dump_artifacts(self):
        """失败时自动截图（__exit__ 异常分支调用），复用主动截图逻辑。"""
        self.screenshot_to_artifact(
            "failure", step="失败时自动截图", category="failure",
        )

    def _dump_trace(self):
        """trace 产物（QA_UI_TRACE=1 时）"""
        art_dir = os.environ.get("QA_ARTIFACT_DIR")
        if not art_dir:
            return
        os.makedirs(art_dir, exist_ok=True)
        try:
            self.browser.stop_tracing(
                path=os.path.join(art_dir, "trace.zip"),
            )
        except Exception:
            pass

    def _write_manifest(self):
        """落盘截图清单 manifest.json（executor 读取后合并进 artifacts 字段）。

        清单格式：[{"name","category","step","order","timestamp"}, ...]
        无 QA_ARTIFACT_DIR 或无截图时不写文件。
        """
        art_dir = os.environ.get("QA_ARTIFACT_DIR")
        if not art_dir or not self._artifacts_meta:
            return
        try:
            os.makedirs(art_dir, exist_ok=True)
            path = os.path.join(art_dir, MANIFEST_FILENAME)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._artifacts_meta, f, ensure_ascii=False)
        except Exception:
            pass
