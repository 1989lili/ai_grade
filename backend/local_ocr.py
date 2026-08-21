# -*- coding: utf-8 -*-
"""本地 OCR 引擎 —— PP-OCRv3 中文识别，纯离线运行，无需云端。

基于 RapidOCR (ONNX Runtime)，首次调用自动加载模型，后续调用直接推理。
模型文件随 PyInstaller 打包进 EXE，无需额外下载。
"""

import logging
import threading

log = logging.getLogger('ai_grade')

_engine = None
_lock = threading.Lock()
_ready = False
_error = None


def _get_engine():
    """获取全局单例引擎（线程安全，延迟初始化）。"""
    global _engine, _ready, _error
    if _ready:
        return _engine
    if _error:
        raise RuntimeError(_error)

    with _lock:
        if _ready:
            return _engine
        if _error:
            raise RuntimeError(_error)
        try:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR(
                text_score=0.4,
                min_height=15,
                width_height_ratio=10,
            )
            _ready = True
            log.info('本地 OCR 引擎就绪 (PP-OCRv3 / ONNX)')
            return _engine
        except Exception as exc:
            _error = f'本地 OCR 初始化失败: {exc}'
            log.exception(_error)
            raise RuntimeError(_error) from exc


def _prefetch():
    """后台预加载模型，减少首次调用延迟。"""
    try:
        import numpy as np
        engine = _get_engine()
        engine(np.zeros((100, 100, 3), dtype='uint8'))
        log.info('本地 OCR 预热完成')
    except Exception:
        pass


# 启动后台预加载
import _thread
try:
    _thread.start_new_thread(_prefetch, ())
except Exception:
    pass


class LocalOCRError(Exception):
    def __init__(self, message, code='local_ocr_failed'):
        super().__init__(message)
        self.message = message
        self.code = code


def call_local_ocr(image_bytes, mime_type='image/jpeg'):
    """对图片字节执行本地 OCR，返回 {'text', 'words_count', 'raw'}。"""
    if not image_bytes:
        raise LocalOCRError('输入图片为空', 'local_ocr_empty_image')

    import time
    import numpy as np
    from io import BytesIO
    from PIL import Image

    started = time.monotonic()

    # ── 解码图片 ──
    try:
        img = Image.open(BytesIO(image_bytes))
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        w, h = img.size
        if max(w, h) > 2048:
            scale = 2048 / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        img_array = np.array(img)
    except Exception as exc:
        raise LocalOCRError(f'图片解码失败: {exc}', 'local_ocr_decode') from exc

    # ── OCR 推理 ──
    ocr_started = time.monotonic()
    try:
        engine = _get_engine()
        result, elapse = engine(img_array)
    except RuntimeError:
        raise
    except Exception as exc:
        raise LocalOCRError(f'OCR 识别失败: {exc}', 'local_ocr_infer') from exc

    ocr_ms = int((time.monotonic() - ocr_started) * 1000)

    # ── 组装结果 ──
    text_parts = []
    raw_items = []
    if result:
        for box, words, confidence in result:
            s = (words or '').strip()
            if s:
                text_parts.append(s)
                raw_items.append({'words': s, 'confidence': float(confidence), 'box': box})

    text = '\n'.join(text_parts)
    total_ms = int((time.monotonic() - started) * 1000)

    log.info('本地OCR: %d字, ocr=%dms, total=%dms', len(text), ocr_ms, total_ms)

    return {
        'text': text,
        'words_count': len(text_parts),
        'raw': raw_items,
    }
