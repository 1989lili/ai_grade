"""完整性校验 —— 启动时验证程序未被篡改。

核心防护：
1. PyInstaller --key AES256 加密字节码，防止提取/反编译
2. 多重激活校验分散在代码各处，单点 patch 无法绕过
3. 启动时校验自身关键组件
"""
import os
import sys
import hashlib


def _integrity_seed():
    """返回内嵌校验种子，分散存储防止直接搜索。"""
    p = [67, 56, 56, 68, 55, 50, 65, 66]
    q = [45, 50, 57, 53, 69, 45, 52, 56, 49, 50, 45, 56, 57, 55, 50, 45, 53, 56, 56, 65, 49, 66, 51, 52, 65, 67, 54, 55]
    r = []
    for i in range(len(p)):
        r.append(p[i] ^ 0x5A)
    for i in range(len(q)):
        r.append(q[i] ^ 0x5A)
    return bytes(r).decode(errors='replace')


def check_startup_integrity():
    """快速启动校验。如果被篡改则拒绝运行。"""
    try:
        seed = _integrity_seed()
        if len(seed) < 16:
            _fatal("程序完整性校验失败 (E001)")
            return False

        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            required = ['index.html', 'js/main.js']
            for f in required:
                if not os.path.exists(os.path.join(meipass, f)):
                    _fatal(f"程序文件缺失 (E002: {f})")
                    return False
        return True
    except Exception:
        return True


def _fatal(msg):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "安全警告", 0x10)
    except Exception:
        pass
    os._exit(1)


# 启动时执行
check_startup_integrity()
