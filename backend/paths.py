# -*- coding: utf-8 -*-
"""运行时可写数据目录。

统一放在 %APPDATA%\\AI_Grader（与激活文件 license.dat 同一处），好处：
1. exe 所在目录不再产生任何文件，绿色目录保持干净，也便于放进 Program Files 等只读位置；
2. 升级/替换 exe 不会弄丢预设、评分标准模板和标记位置。

老版本把这些文件写在 exe 同级目录，这里提供一次性自动迁移（复制，不删原件，便于回退）。
"""

import os
import shutil
import sys

APP_DIR_NAME = 'AI_Grader'


def get_app_data_dir():
    """返回（并创建）%APPDATA%\\AI_Grader 数据目录。"""
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    path = os.path.join(base, APP_DIR_NAME)
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def _legacy_dirs():
    """历史版本存放数据的位置：打包版 = exe 同级；源码版 = backend/ 与项目 dist/。"""
    dirs = []
    if getattr(sys, 'frozen', False):
        dirs.append(os.path.dirname(sys.executable))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        dirs.append(here)
        dirs.append(os.path.normpath(os.path.join(here, '..', 'dist')))
    return dirs


def data_file(filename):
    """数据文件的规范路径（%APPDATA%\\AI_Grader\\filename）。

    若新位置不存在、而老位置存在同名文件，则自动复制过来完成迁移。
    """
    target = os.path.join(get_app_data_dir(), filename)
    if os.path.exists(target):
        return target
    for folder in _legacy_dirs():
        old = os.path.join(folder, filename)
        if os.path.normpath(old) == os.path.normpath(target):
            continue
        if os.path.isfile(old):
            try:
                shutil.copy2(old, target)
            except Exception:
                pass
            break
    return target
