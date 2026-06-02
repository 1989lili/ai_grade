# -*- mode: python ; coding: utf-8 -*-
"""管理端构建 —— 仅管理员持有，绝不随用户版分发。"""
from PyInstaller.utils.hooks import collect_submodules, collect_all
import os
import sys

block_cipher = None

conda_bin = os.path.join(sys.prefix, 'Library', 'bin')

flask_datas, flask_binaries, flask_hiddenimports = collect_all('flask')
werkzeug_datas, werkzeug_binaries, werkzeug_hiddenimports = collect_all('werkzeug')
webview_datas, webview_binaries, webview_hiddenimports = collect_all('webview')

a = Analysis(
    ['backend/admin_launcher.py'],
    pathex=['backend'],
    binaries=flask_binaries + werkzeug_binaries + webview_binaries + [
        (os.path.join(conda_bin, 'ffi.dll'), '.'),
        (os.path.join(conda_bin, 'sqlite3.dll'), '.'),
        (os.path.join(conda_bin, 'liblzma.dll'), '.'),
        (os.path.join(conda_bin, 'libbz2.dll'), '.'),
        (os.path.join(conda_bin, 'libmpdec-4.dll'), '.'),
        (os.path.join(conda_bin, 'libexpat.dll'), '.'),
    ],
    datas=[
    ] + flask_datas + werkzeug_datas + webview_datas,
    hiddenimports=[
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'pystray',
        'queue',
        'json',
        're',
        'base64',
        'datetime',
        'crypto',
        'hwid',
        'license',
        'license_gen',
        'db',
        'admin',
        'flask_cors',
        'cryptography',
        'cryptography.hazmat.primitives.ciphers.aead',
        'cryptography.hazmat.primitives.asymmetric.padding',
        'cryptography.hazmat.backends',
        'webview',
        'webview.platforms.edgechromium',
        'webview.http',
        'bottle',
        'proxy_tools',
        'clr_loader',
        'requests',
    ] + flask_hiddenimports + werkzeug_hiddenimports + webview_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'test', 'unittest', 'xmlrpc', 'mss', 'pyautogui', 'pyscreeze', 'pygetwindow'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AI_Grader_Admin',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
