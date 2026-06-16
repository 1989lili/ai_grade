# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules, collect_all
import os
import sys

block_cipher = None

conda_bin = os.path.join(sys.prefix, 'Library', 'bin')

# Collect all package data
flask_datas, flask_binaries, flask_hiddenimports = collect_all('flask')
werkzeug_datas, werkzeug_binaries, werkzeug_hiddenimports = collect_all('werkzeug')
webview_datas, webview_binaries, webview_hiddenimports = collect_all('webview')

a = Analysis(
    ['backend/launcher.py'],
    pathex=['backend'],
    binaries=flask_binaries + werkzeug_binaries + webview_binaries + [
        (os.path.join(conda_bin, 'ffi.dll'), '.'),
        (os.path.join(conda_bin, 'sqlite3.dll'), '.'),
        (os.path.join(conda_bin, 'liblzma.dll'), '.'),
        (os.path.join(conda_bin, 'libbz2.dll'), '.'),
        (os.path.join(conda_bin, 'libexpat.dll'), '.'),
        (os.path.join(conda_bin, 'tcl86t.dll'), '.'),
        (os.path.join(conda_bin, 'tk86t.dll'), '.'),
    ],
    datas=[
        ('index.html', '.'),
        ('js/main.js', 'js/'),
        ('css/style.css', 'css/'),
    ] + flask_datas + werkzeug_datas + webview_datas,
    hiddenimports=[
        'mss',
        'mss.tools',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'pyautogui',
        'pyperclip',
        'pyscreeze',
        'pygetwindow',
        'pymsgbox',
        'mouseinfo',
        'pytweening',
        'requests',
        'cryptography',
        'cryptography.hazmat.primitives.ciphers.aead',
        'cryptography.hazmat.primitives.asymmetric.padding',
        'cryptography.hazmat.backends',
        'pystray',
        'queue',
        'json',
        're',
        'base64',
        'datetime',
        'traceback',
        'crypto',
        'hwid',
        'license',
        'activation_ui',
        'integrity',
        'grading_prompts',
        'zhipu_ocr',
        'tkinter',
        'queue',
        'flask_cors',
        'webview',
        'webview.platforms.edgechromium',
        'webview.http',
        'bottle',
        'proxy_tools',
        'clr_loader',
    ] + flask_hiddenimports + werkzeug_hiddenimports + webview_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['test', 'unittest', 'xmlrpc'],
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
    name='AI_Grader',
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
