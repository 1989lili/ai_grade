# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules, collect_all
import os
import sys

block_cipher = None

# UPX 压缩：cv2/onnxruntime/numpy 等大二进制可压至 ~60% 体积
_UPX_DIR = os.path.abspath(os.path.join(SPECPATH, 'tools', 'upx', 'upx-4.2.4-win64'))
if os.path.isdir(_UPX_DIR):
    os.environ['PATH'] = _UPX_DIR + os.pathsep + os.environ.get('PATH', '')

conda_bin = os.path.join(sys.prefix, 'Library', 'bin')

# Collect all package data
flask_datas, flask_binaries, flask_hiddenimports = collect_all('flask')
werkzeug_datas, werkzeug_binaries, werkzeug_hiddenimports = collect_all('werkzeug')
webview_datas, webview_binaries, webview_hiddenimports = collect_all('webview')
rapidocr_datas, rapidocr_binaries, rapidocr_hiddenimports = collect_all('rapidocr_onnxruntime')

# onnxruntime 依赖的 DLL 较大，PyInstaller 通过 hook 收集；这里显式补上 conda 动态库
try:
    onnxruntime_bin_dir = os.path.join(sys.prefix, 'Lib', 'site-packages', 'onnxruntime', 'capi')
    _ort_bins = [(os.path.join(onnxruntime_bin_dir, f), 'onnxruntime/capi') for f in os.listdir(onnxruntime_bin_dir) if f.endswith('.dll')]
except Exception:
    _ort_bins = []

a = Analysis(
    ['backend/launcher.py'],
    pathex=['backend'],
    binaries=flask_binaries + werkzeug_binaries + webview_binaries + rapidocr_binaries + _ort_bins + [
        (os.path.join(conda_bin, 'ffi.dll'), '.'),
        (os.path.join(conda_bin, 'sqlite3.dll'), '.'),
        (os.path.join(conda_bin, 'liblzma.dll'), '.'),
        (os.path.join(conda_bin, 'libbz2.dll'), '.'),
        (os.path.join(conda_bin, 'libexpat.dll'), '.'),
        (os.path.join(conda_bin, 'tcl86t.dll'), '.'),
        (os.path.join(conda_bin, 'tk86t.dll'), '.'),
        # Python ssl/hashlib 依赖 OpenSSL 动态库，缺失会导致 https 请求失败
        (os.path.join(conda_bin, 'libcrypto-3-x64.dll'), '.'),
        (os.path.join(conda_bin, 'libssl-3-x64.dll'), '.'),
    ],
    datas=[
        ('index.html', '.'),
        ('js/main.js', 'js/'),
        ('css/style.css', 'css/'),
    ] + flask_datas + werkzeug_datas + webview_datas + rapidocr_datas,
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
        'local_ocr',
        'numpy',
        'cv2',
        'onnxruntime',
        'onnxruntime.capi',
        'rapidocr_onnxruntime',
        'tkinter',
        'queue',
        'flask_cors',
        'webview',
        'webview.platforms.edgechromium',
        'webview.http',
        'bottle',
        'proxy_tools',
        'clr_loader',
    ] + flask_hiddenimports + werkzeug_hiddenimports + webview_hiddenimports + rapidocr_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['test', 'unittest', 'xmlrpc'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 裁剪不需要的二进制：opencv 视频编解码 DLL（本地 OCR 用不到，约 -29MB）
a.binaries = [b for b in a.binaries if 'opencv_videoio_ffmpeg' not in b[0]]

# 统一 VC 运行库版本：PyInstaller 可能收集到旧版(14.36)，与 onnxruntime 依赖的 14.44 混用会导致 DLL 初始化失败
_VC_DLLS = ['vcruntime140.dll', 'vcruntime140_1.dll', 'vcruntime140_threads.dll',
            'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
            'msvcp140_atomic_wait.dll', 'msvcp140_codecvt_ids.dll']
a.binaries = [b for b in a.binaries if os.path.basename(b[1]) not in _VC_DLLS]
a.binaries += [(d, os.path.join(sys.prefix, d), 'BINARY') for d in _VC_DLLS
               if os.path.exists(os.path.join(sys.prefix, d))]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AI_Grader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AI_Grader',
)
