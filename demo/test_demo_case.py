"""演示用例：用于端到端验证代码用例平台流程
（远程仓库拉取用例 -> 平台扫描入库 -> 查看用例代码 -> 执行 -> 获取执行结果）

用例不依赖外部环境，可独立执行通过。
"""
from app.modules.code_case.decorators import case


@case(module="演示项目-示例模块", name="演示用例-求和校验", level="P1",
      description="验证 1 + 1 == 2，用于端到端验证平台流程", project="演示项目")
def test_demo_sum():
    print("[演示用例] 开始执行：求和校验")
    result = 1 + 1
    print(f"[演示用例] 计算结果 result={result}")
    assert result == 2, "1 + 1 应当等于 2"
    print("[演示用例] 执行完成：通过")


@case(module="演示项目-示例模块", name="演示用例-列表逆序校验", level="P2",
      description="验证列表逆序结果正确，用于端到端验证平台流程", project="演示项目")
def test_demo_list_reverse():
    print("[演示用例] 开始执行：列表逆序校验")
    source = [1, 2, 3]
    reversed_list = list(reversed(source))
    print(f"[演示用例] 原列表={source} 逆序={reversed_list}")
    assert reversed_list == [3, 2, 1], "逆序结果应为 [3, 2, 1]"
    print("[演示用例] 执行完成：通过")


@case(module="演示项目-示例模块", name="演示用例-远程拉取校验", level="P1",
      description="仅存在于远程仓库，用于验证平台从 GitHub 仓库拉取用例后自动入库", project="演示项目")
def test_demo_remote_pull():
    print("[演示用例] 开始执行：远程拉取校验")
    payload = {"source": "github", "repo": "code_case_warehouse"}
    print(f"[演示用例] 用例来源信息={payload}")
    assert payload["source"] == "github", "用例应来源于远程 GitHub 仓库"
    print("[演示用例] 执行完成：通过")
