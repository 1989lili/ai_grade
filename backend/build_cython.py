"""编译关键模块为 .pyd 原生二进制。运行: python build_cython.py"""
import os
import sys
import subprocess
import hashlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 需要编译的核心安全模块
MODULES = [
    'license.py',
    'crypto.py',
    'hwid.py',
]


def compile_module(py_file):
    """使用 Cython 将 .py 编译为 .pyd"""
    path = os.path.join(BASE_DIR, py_file)
    if not os.path.exists(path):
        print(f"  SKIP: {py_file} not found")
        return False

    # 1. Cython .py -> .c
    print(f"  Cython: {py_file} -> .c")
    result = subprocess.run(
        [sys.executable, '-m', 'cython', '--embed', '0', '-3', path],
        capture_output=True, text=True, cwd=BASE_DIR
    )
    if result.returncode != 0:
        print(f"  ERROR (cython): {result.stderr}")
        return False

    # 2. MSVC: .c -> .pyd
    c_file = py_file.replace('.py', '.c')
    pyd_file = py_file.replace('.py', '.pyd')

    # Get Python include and libs
    import sysconfig
    include_dir = sysconfig.get_path('include')
    libs_dir = sysconfig.get_config_var('LIBDIR') or os.path.join(sys.prefix, 'libs')
    python_lib = f'python{sys.version_info.major}{sys.version_info.minor}'

    cl_cmd = [
        'cl',
        '/nologo', '/O2', '/GL',
        f'/I{include_dir}',
        '/MD',
        '/LD',
        f'/Fe{os.path.join(BASE_DIR, pyd_file)}',
        f'{os.path.join(BASE_DIR, c_file)}',
        f'/link',
        f'/LIBPATH:{libs_dir}',
        f'{python_lib}.lib',
    ]

    print(f"  MSVC: {c_file} -> {pyd_file}")
    result = subprocess.run(cl_cmd, capture_output=True, text=True, cwd=BASE_DIR)
    if result.returncode != 0:
        print(f"  NOTE: MSVC not found or failed, trying setuptools approach...")
        # Fallback: use setuptools
        return compile_with_setuptools(py_file)
    return True


def compile_with_setuptools(py_file):
    """Fallback: use setuptools + Cython to build .pyd"""
    from setuptools import setup, Extension
    from Cython.Build import cythonize
    import numpy

    name = py_file.replace('.py', '')
    ext = Extension(
        name,
        sources=[py_file],
        extra_compile_args=['/O2', '/GL'] if sys.platform == 'win32' else ['-O3'],
    )

    try:
        setup(
            name=name,
            ext_modules=cythonize(
                [ext],
                compiler_directives={'language_level': '3'},
            ),
            script_args=['build_ext', '--inplace'],
            script_name='setup_cython',
        )
        return True
    except Exception as e:
        print(f"  ERROR (setuptools): {e}")
        return False


def compute_hashes():
    """计算编译后 .pyd 文件的 SHA256，用于完整性校验"""
    hashes = {}
    for m in MODULES:
        pyd = m.replace('.py', '.pyd')
        path = os.path.join(BASE_DIR, pyd)
        if os.path.exists(path):
            with open(path, 'rb') as f:
                hashes[pyd] = hashlib.sha256(f.read()).hexdigest()
    return hashes


def main():
    os.chdir(BASE_DIR)
    print("=== Cython 编译核心模块 ===")
    for m in MODULES:
        print(f"Compiling {m}...")
        compile_with_setuptools(m)
    print("\nDone.")


if __name__ == '__main__':
    main()
