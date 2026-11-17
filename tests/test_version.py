import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_shared_version_scheme_rolls_over_at_99():
    from version import versions
    assert versions(96) == {"android": "0.1.96", "pc": "0.1.196", "code": 96}
    assert versions(99) == {"android": "0.1.99", "pc": "0.1.199", "code": 99}
    assert versions(100) == {"android": "0.2.0", "pc": "0.2.0", "code": 100}                 # tới .99 / .199 thì cả hai lên 0.2.0
    assert versions(199)["android"] == "0.2.99" and versions(200)["pc"] == "0.3.0"          # 0.2.99 rồi 0.3.0


def test_android_code_from_version_is_monotonic_across_rollover():
    from pp import updater
    codes = [updater.android_code(v) for v in ("0.1.95", "0.1.99", "0.2.0", "0.2.99", "0.3.0")]
    assert codes == [95, 99, 100, 199, 200] and codes == sorted(codes)
    assert updater.is_newer("0.2.0", "0.1.199") and updater.is_newer("0.3.0", "0.2.99")
