# -*- coding: utf-8 -*-
"""智谱 GLM-OCR 手写识别封装（multipart 上传，同步返回）。

接口规格基于 zai-sdk 0.2.2 源码:
- POST https://open.bigmodel.cn/api/paas/v4/files/ocr
- Content-Type: multipart/form-data
- file (binary) + tool_type=hand_write [+ probability + language_type]
- 响应: {task_id, status, message, words_result_num, words_result:[{words,location,probability}]}
"""

import logging
import requests

OCR_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/files/ocr"

log = logging.getLogger('ai_grade')


class OCRError(Exception):
    """OCR 调用失败的统一异常。"""

    def __init__(self, message, code='ocr_failed', detail=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.detail = detail


def call_handwriting_ocr(api_key, image_bytes, mime_type='image/jpeg',
                         filename='card.jpg', connect_timeout=3, read_timeout=8,
                         language_type=None, probability=True):
    """同步调用智谱手写 OCR，返回 {text, words_count, raw}。

    抛 OCRError（含连接/超时/HTTP/业务错误）。
    """
    if not api_key:
        raise OCRError('请先在AI配置页面填写智谱 OCR API Key', code='ocr_missing_key')
    if not image_bytes:
        raise OCRError('OCR 输入图片为空', code='ocr_empty_image')

    headers = {"Authorization": f"Bearer {api_key}"}
    files = {"file": (filename, image_bytes, mime_type)}
    data = {"tool_type": "hand_write"}
    if probability:
        data["probability"] = "true"
    if language_type:
        data["language_type"] = language_type

    log.info("OCR 请求: bytes=%d, mime=%s", len(image_bytes), mime_type)
    try:
        resp = requests.post(
            OCR_ENDPOINT,
            headers=headers,
            files=files,
            data=data,
            timeout=(connect_timeout, read_timeout),
        )
    except requests.exceptions.ConnectTimeout as exc:
        raise OCRError('OCR 连接超时，请检查网络', code='ocr_connect_timeout') from exc
    except requests.exceptions.ReadTimeout as exc:
        raise OCRError(f'OCR 响应超时（>{read_timeout}s）', code='ocr_read_timeout') from exc
    except requests.exceptions.ConnectionError as exc:
        raise OCRError('OCR 网络连接失败', code='ocr_connection_error') from exc
    except requests.exceptions.RequestException as exc:
        raise OCRError(f'OCR 请求失败：{exc}', code='ocr_request_error') from exc

    if resp.status_code in (401, 403):
        raise OCRError('智谱 OCR API Key 无效或无权限', code='ocr_auth_error')
    if resp.status_code == 429:
        raise OCRError('智谱 OCR 限流，请稍后重试', code='ocr_rate_limited')
    if resp.status_code >= 400:
        raise OCRError(f'OCR 服务返回 HTTP {resp.status_code}: {resp.text[:200]}',
                       code='ocr_http_error')

    try:
        body = resp.json()
    except ValueError as exc:
        raise OCRError('OCR 响应非 JSON', code='ocr_invalid_json') from exc

    # 智谱 OCR 失败时通常返回 status != 'success' 或 message 为非空错误
    status = body.get('status')
    if status and str(status).lower() not in ('success', 'ok', '0'):
        raise OCRError(f'OCR 失败：{body.get("message") or status}',
                       code='ocr_business_error', detail=body)

    words = body.get('words_result') or []
    text_parts = []
    for w in words:
        s = (w.get('words') or '').strip()
        if s:
            text_parts.append(s)
    text = '\n'.join(text_parts)

    log.info("OCR 完成: words=%d, text_len=%d", len(words), len(text))
    return {
        'text': text,
        'words_count': len(words),
        'raw': body,
    }
