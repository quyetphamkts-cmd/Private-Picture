"""Số phiên bản chung cho app PC và app Android (cùng một lần dựng, cùng một bộ đếm).

M = số trong tệp VERSION — chỉ tăng 1 khi bạn bảo nâng phiên bản; PC và Android luôn dùng chung M nên cùng nâng cấp một thể.
  M ≤ 99 : Android 0.1.M, PC 0.1.(M+100)   (giai đoạn chuyển tiếp từ các số cũ: Android 0.1.9x, PC 0.1.19x)
  M ≥ 100: cả hai cùng số: 0.2.0 … 0.2.99, rồi 0.3.0 … 0.3.99, v.v.
versionCode của Android chính là M (luôn tăng, không bị tụt khi sang bản 0.2.0).
"""
import os
import sys


def versions(m):
    if m <= 99:
        return {"android": f"0.1.{m}", "pc": f"0.1.{m + 100}", "code": m}
    minor, patch = 2 + (m - 100) // 100, (m - 100) % 100
    v = f"0.{minor}.{patch}"
    return {"android": v, "pc": v, "code": m}


def current_m(root="."):
    """M đọc từ tệp VERSION (số nguyên). Chỉ tăng khi bạn bảo nâng phiên bản: mọi lần dựng giữa hai lần nâng đều mang cùng một số."""
    return int(open(os.path.join(root, "VERSION")).read().strip())


if __name__ == "__main__":
    v = versions(current_m())
    which = sys.argv[1] if len(sys.argv) > 1 else "android"
    if which == "android":
        print(f"PP_VERSION_NAME={v['android']}\nPP_VERSION_CODE={v['code']}")
    else:
        print(f"PP_VERSION_NAME={v['pc']}")
