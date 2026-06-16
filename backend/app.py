from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS
import os
import sys
import json
import datetime
import base64
import re
import html
import requests
import traceback
import time
import threading
import queue
import logging
from logging.handlers import RotatingFileHandler

try:
    from .crypto import secure_read_json, secure_write_json
    from .license import is_activated, validate_license_key, store_license
    from .activation_ui import ACTIVATION_HTML
    from .hwid import generate_hwid
except ImportError:
    from crypto import secure_read_json, secure_write_json  # type: ignore
    from license import is_activated, validate_license_key, store_license  # type: ignore
    from activation_ui import ACTIVATION_HTML  # type: ignore
    from hwid import generate_hwid  # type: ignore

app = Flask(__name__)
app.secret_key = 'ai_grade_admin_secret_2026'
CORS(app)

ACTIVATED = False

# ---------- 日志配置 ----------

def setup_logging():
    """配置文件日志到 dist 目录，支持轮转（单文件最大 5MB，保留 3 个备份）。"""
    if getattr(sys, 'frozen', False):
        log_dir = os.path.join(os.path.dirname(sys.executable), 'dist')
    else:
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dist')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'ai_grade.log')

    logger = logging.getLogger('ai_grade')
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger

    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # 开发模式下也输出到控制台
    if not getattr(sys, 'frozen', False):
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    logger.info('=' * 50)
    logger.info('好帮手AI阅卷 启动日志记录')
    logger.info(f'日志文件: {log_file}')
    return logger

log = setup_logging()


def check_activation():
    global ACTIVATED
    ACTIVATED = is_activated()
    return ACTIVATED

# ---------- 路径解析 ----------

if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
    EXE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    EXE_DIR = os.path.dirname(os.path.abspath(__file__))

PRESETS_FILE = os.path.join(EXE_DIR, 'presets.json')

# ---------- 静态文件服务 ----------

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_static(path):
    if path == '':
        return send_from_directory(BASE_DIR, 'index.html')
    else:
        return send_from_directory(BASE_DIR, path)


# ---------- 激活检查中间件 ----------

@app.before_request
def require_activation():
    if request.path.startswith('/api/') and request.path not in ('/api/hwid', '/api/activate'):
        if not check_activation():
            return jsonify({'status': 'error', 'message': '软件未激活，请先激活'}), 403


# ---------- 屏幕截取 ----------

def capture_screen(x, y, w, h):
    """用 mss 截取屏幕指定区域，返回 PNG 字节"""
    import mss
    import mss.tools
    monitor = {"top": int(y), "left": int(x), "width": int(w), "height": int(h)}
    with mss.mss() as sct:
        sct_img = sct.grab(monitor)
        return mss.tools.to_png(sct_img.rgb, sct_img.size)


def capture_screen_base64(x, y, w, h):
    """截屏并返回预处理后的 base64 字符串与元数据。

    返回 dict:
      base64    - 图像 base64
      mime_type - 'image/jpeg' 或 'image/png'（PIL 失败回退）
      meta      - 预处理元信息（输入/输出字节、是否缩放、尺寸）
    """
    png_bytes = capture_screen(x, y, w, h)
    processed_bytes, mime_type, meta = preprocess_card_image(png_bytes)
    return {
        'base64': base64.b64encode(processed_bytes).decode('utf-8'),
        'mime_type': mime_type,
        'meta': meta,
    }


# ---------- 图像预处理 ----------

# 长边压缩到 1600px 内 + JPEG 70% 质量；目标输出 80~200KB。
# 同时大幅减小上传体积（4K 截图原始 PNG 可达数 MB）。
PREPROCESS_MAX_LONG_EDGE = 1600
PREPROCESS_JPEG_QUALITY = 70


def preprocess_card_image(png_bytes):
    """把答题卡截图压缩为 JPEG。失败则原 PNG 兜底。"""
    input_bytes = len(png_bytes)
    try:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(png_bytes))
        # JPEG 不支持 alpha，转 RGB
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        orig_w, orig_h = img.size
        long_edge = max(orig_w, orig_h)
        resized = False
        if long_edge > PREPROCESS_MAX_LONG_EDGE:
            scale = PREPROCESS_MAX_LONG_EDGE / float(long_edge)
            new_size = (max(1, int(orig_w * scale)), max(1, int(orig_h * scale)))
            img = img.resize(new_size, Image.LANCZOS)
            resized = True
        out = BytesIO()
        img.save(out, format='JPEG', quality=PREPROCESS_JPEG_QUALITY, optimize=True)
        out_bytes = out.getvalue()
        meta = {
            'input_bytes': input_bytes,
            'output_bytes': len(out_bytes),
            'width': img.size[0],
            'height': img.size[1],
            'resized': resized,
            'fallback': False,
        }
        log.info('图片预处理: png=%d, jpeg=%d, resized=%s, size=%dx%d',
                 input_bytes, len(out_bytes), resized, img.size[0], img.size[1])
        return out_bytes, 'image/jpeg', meta
    except Exception as exc:
        log.warning('图片预处理失败，回退到原 PNG: %s', exc)
        meta = {
            'input_bytes': input_bytes,
            'output_bytes': input_bytes,
            'width': 0,
            'height': 0,
            'resized': False,
            'fallback': True,
        }
        return png_bytes, 'image/png', meta


# ---------- 桌面自动化 ----------

HUMAN_ACTION_DELAY = 0.1  # 桌面自动化短暂停顿，等待输入框响应
HUMAN_SCORE_PAUSE = 1.5  # 写完分数后停顿 1.5 秒再提交


def auto_fill_score(x, y, score):
    """在指定屏幕位置填入分数——模拟人类操作，每步之间有停顿"""
    import pyautogui
    import pyperclip
    sx, sy = int(x), int(y)
    log.info("填分: 准备在 (%d, %d) 填入 %s", sx, sy, score)
    pyperclip.copy(str(score))
    # 点击目标位置
    time.sleep(HUMAN_ACTION_DELAY)
    pyautogui.click(sx, sy)
    pyautogui.sleep(HUMAN_ACTION_DELAY)
    # 全选
    pyautogui.hotkey('ctrl', 'a')
    pyautogui.sleep(HUMAN_ACTION_DELAY)
    # 粘贴
    pyautogui.hotkey('ctrl', 'v')
    pyautogui.sleep(HUMAN_ACTION_DELAY)
    log.info("填分: 已粘贴分数 %s", score)


def auto_click_submit(x, y):
    """点击提交按钮"""
    import pyautogui
    bx, by = int(x), int(y)
    log.info("提交: 点击 (%d, %d)", bx, by)
    time.sleep(HUMAN_ACTION_DELAY)
    pyautogui.click(bx, by)
    log.info("提交: 已点击")


# ---------- 多模态 LLM 调用 ----------

LLM_CONNECT_TIMEOUT = 5
LLM_READ_TIMEOUT = 30
LLM_MAX_RETRIES = 1
LLM_RETRY_BACKOFF_SECONDS = 2
LLM_MAX_TOKENS = 1024
LLM_STREAM_MAX_TOKENS = 400
# 流式调用首包（首个 token 或 reasoning 片段）必须在该秒数内到达，否则视为超时
LLM_FIRST_BYTE_TIMEOUT = 8


class GradingError(Exception):
    def __init__(self, message, code='grading_error', status_code=500, detail=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.detail = detail


from grading_prompts import (
    GRADING_SYSTEM_PROMPT,
    GRADING_STREAM_SYSTEM_PROMPT,
    GRADING_TEXT_STREAM_SYSTEM_PROMPT,
)

try:
    from .zhipu_ocr import call_handwriting_ocr, OCRError
except ImportError:
    from zhipu_ocr import call_handwriting_ocr, OCRError  # type: ignore


def html_to_text(value):
    """将编辑器保存的 HTML 内容转为适合发给模型的纯文本。"""
    if not value:
        return ''
    text = str(value)
    text = re.sub(r'<\s*br\s*/?\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</\s*(div|p|li|h[1-6])\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def build_grading_messages(image_base64, standards, streaming=False, image_mime_type='image/png',
                           ocr_text=None):
    """构建 grading prompt。

    - ocr_text 非空：纯文本路径（OCR 已完成手写识别），不附图片
    - ocr_text 为空：原多模态路径（图片 + 评分标准）
    """
    use_text_path = bool(ocr_text and ocr_text.strip())
    parts = []

    if not use_text_path:
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{image_mime_type};base64,{image_base64}"}
        })

    material = html_to_text(standards.get('material', ''))
    answer = html_to_text(standards.get('answer', ''))
    example = html_to_text(standards.get('example', ''))
    requirement = html_to_text(standards.get('requirement', ''))

    text_parts = []
    if use_text_path:
        text_parts.append("请对下面的学生作答进行评分。")
        text_parts.append(f"【学生作答（OCR识别）】\n{ocr_text.strip()}")
    else:
        text_parts.append("请对下面的答题卡截图进行评分。")

    if material:
        text_parts.append(f"【题目材料】\n{material}")
    if answer:
        text_parts.append(f"【参考答案】\n{answer}")
    if example:
        text_parts.append(f"【评价示例】\n{example}")
    if requirement:
        text_parts.append(f"【评分要求】\n{requirement}")

    if streaming:
        text_parts.append(
            "请快速评分。开头必须直接输出：得分：<score>/<max_score>，简评：<一句话>。"
            "不要输出铺垫语、思考过程或 Markdown。最后一行输出一个可解析的 JSON：\n"
            "{\"student_answer\":\"<原作答>\",\"review_analysis\":\"<1-2句>\",\"score\":<数字>,\"max_score\":<数字>,\"reasoning\":\"<一句话依据>\"}"
        )
    else:
        text_parts.append(
            "只返回 JSON："
            "{\"student_answer\":\"<作答>\",\"review_analysis\":\"<评析>\",\"score\":<数字>,\"max_score\":<数字>,\"reasoning\":\"<依据>\"}"
        )

    parts.append({"type": "text", "text": "\n\n".join(text_parts)})

    if streaming:
        system_prompt = GRADING_TEXT_STREAM_SYSTEM_PROMPT if use_text_path else GRADING_STREAM_SYSTEM_PROMPT
    else:
        system_prompt = GRADING_SYSTEM_PROMPT
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": parts}
    ]


def get_provider_api_url(provider):
    if provider == 'doubao':
        return "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    if provider == 'deepseek':
        return "https://api.deepseek.com/v1/chat/completions"
    if provider == 'zhipu':
        return "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    raise GradingError(f"不支持的服务商: {provider}", code='unsupported_provider', status_code=400)


def raise_for_model_status(response):
    status = response.status_code
    if status < 400:
        return
    if status in (401, 403):
        raise GradingError('API Key无效或无权限，请检查AI配置。', code='model_auth_error', status_code=400)
    if status == 429:
        raise GradingError('模型服务限流，请稍后重试。', code='model_rate_limited', status_code=502)
    if status in (408, 500, 502, 503, 504):
        raise GradingError('模型服务暂时异常，请稍后重试。', code='model_server_error', status_code=502,
                           detail=f'HTTP {status}')
    raise GradingError(f'模型服务请求失败，HTTP状态码：{status}', code='model_http_error', status_code=502)


def make_grading_payload(model_name, image_base64, standards, streaming=False, image_mime_type='image/png',
                         ocr_text=None):
    payload = {
        "model": model_name,
        "messages": build_grading_messages(image_base64, standards, streaming=streaming,
                                           image_mime_type=image_mime_type,
                                           ocr_text=ocr_text),
        "temperature": 0,
        "top_p": 0.1,
        "max_tokens": LLM_STREAM_MAX_TOKENS if streaming else LLM_MAX_TOKENS
    }
    if streaming:
        payload["stream"] = True
    return payload


def call_llm_for_grading(provider, api_key, model_name, image_base64, standards,
                         image_mime_type='image/png', ocr_text=None):
    """调用大模型进行批改，返回响应文本和调用元数据。"""
    api_url = get_provider_api_url(provider)
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    payload = make_grading_payload(model_name, image_base64, standards,
                                   image_mime_type=image_mime_type, ocr_text=ocr_text)

    total_attempts = LLM_MAX_RETRIES + 1
    started = time.monotonic()
    last_error = None

    for attempt in range(1, total_attempts + 1):
        try:
            log.info("模型请求 attempt=%d/%d, timeout=%ds", attempt, total_attempts, LLM_READ_TIMEOUT)
            response = requests.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=(LLM_CONNECT_TIMEOUT, LLM_READ_TIMEOUT)
            )

            response.encoding = 'utf-8'
            if response.status_code in (408, 429, 500, 502, 503, 504) and attempt < total_attempts:
                log.info("模型服务返回 %d，准备重试", response.status_code)
                time.sleep(LLM_RETRY_BACKOFF_SECONDS * attempt)
                continue

            raise_for_model_status(response)

            try:
                result = response.json()
            except ValueError as exc:
                raise GradingError('模型服务返回格式异常，请稍后重试。', code='model_invalid_json',
                                   status_code=502) from exc

            if result and 'choices' in result and len(result['choices']) > 0:
                content = result['choices'][0].get('message', {}).get('content', '')
                if content:
                    duration_ms = int((time.monotonic() - started) * 1000)
                    return {
                        'content': content,
                        'provider': provider,
                        'model': model_name,
                        'attempts': attempt,
                        'duration_ms': duration_ms,
                    }

            raise GradingError('模型响应为空，请稍后重试。', code='model_empty_response', status_code=502)

        except requests.exceptions.ConnectTimeout as exc:
            last_error = exc
            if attempt < total_attempts:
                time.sleep(LLM_RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise GradingError('连接模型服务超时，请检查网络或服务商地址。', code='model_connect_timeout',
                               status_code=504) from exc
        except requests.exceptions.ReadTimeout as exc:
            last_error = exc
            if attempt < total_attempts:
                time.sleep(LLM_RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise GradingError(
                f'模型响应超时，已等待{LLM_READ_TIMEOUT}秒。建议缩小答题卡截图区域、精简评分材料、稍后重试或切换更快模型。',
                code='model_read_timeout', status_code=504) from exc
        except requests.exceptions.ConnectionError as exc:
            last_error = exc
            if attempt < total_attempts:
                time.sleep(LLM_RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise GradingError('连接模型服务失败，请检查网络后重试。', code='model_connection_error',
                               status_code=502) from exc
        except requests.exceptions.RequestException as exc:
            last_error = exc
            raise GradingError('调用模型服务失败，请稍后重试。', code='model_request_error', status_code=502,
                               detail=str(exc)) from exc

    raise GradingError('调用模型服务失败，请稍后重试。', code='model_request_error', status_code=502,
                       detail=str(last_error) if last_error else None)


def stream_llm_for_grading(provider, api_key, model_name, image_base64, standards, out_queue,
                           image_mime_type='image/png', ocr_text=None):
    """流式调用大模型，将 token/error/done 事件放入队列。"""
    api_url = get_provider_api_url(provider)
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "text/event-stream",
        "Authorization": f"Bearer {api_key}"
    }
    payload = make_grading_payload(model_name, image_base64, standards, streaming=True,
                                   image_mime_type=image_mime_type, ocr_text=ocr_text)
    total_attempts = LLM_MAX_RETRIES + 1
    started = time.monotonic()
    content_parts = []
    emitted_token = False
    last_error = None

    for attempt in range(1, total_attempts + 1):
        try:
            if attempt > 1:
                out_queue.put({'type': 'status', 'message': f'模型服务异常，正在第 {attempt} 次重试...'})
            log.info("流式模型请求 attempt=%d/%d", attempt, total_attempts)
            response = requests.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=(LLM_CONNECT_TIMEOUT, LLM_READ_TIMEOUT),
                stream=True
            )

            response.encoding = 'utf-8'
            if response.status_code in (408, 429, 500, 502, 503, 504) and attempt < total_attempts and not emitted_token:
                print(f"[Grade] 流式模型服务返回 {response.status_code}，准备重试")
                time.sleep(LLM_RETRY_BACKOFF_SECONDS * attempt)
                continue

            raise_for_model_status(response)

            for raw_line in response.iter_lines(decode_unicode=False):
                if not raw_line:
                    continue
                try:
                    line = raw_line.decode('utf-8')
                except UnicodeDecodeError:
                    line = raw_line.decode('utf-8', errors='replace')
                line = line.strip()
                if line.startswith('data:'):
                    line = line[5:].strip()
                if not line:
                    continue
                if line == '[DONE]':
                    break
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if chunk.get('error'):
                    message = chunk['error'].get('message') if isinstance(chunk['error'], dict) else str(chunk['error'])
                    raise GradingError(message or '模型流式响应返回错误。', code='model_stream_error', status_code=502)
                choices = chunk.get('choices') or []
                if not choices:
                    continue
                delta = choices[0].get('delta') or {}
                content = delta.get('content') or ''
                reasoning_content = delta.get('reasoning_content') or delta.get('reasoning') or ''
                if reasoning_content:
                    emitted_token = True
                    out_queue.put({'type': 'reasoning', 'content': reasoning_content})
                if content:
                    emitted_token = True
                    content_parts.append(content)
                    out_queue.put({'type': 'token', 'content': content})

            full_text = ''.join(content_parts)
            if not full_text:
                raise GradingError('模型响应为空，请稍后重试。', code='model_empty_response', status_code=502)
            out_queue.put({
                'type': 'done',
                'content': full_text,
                'attempts': attempt,
                'duration_ms': int((time.monotonic() - started) * 1000),
                'provider': provider,
                'model': model_name,
            })
            return

        except requests.exceptions.ConnectTimeout as exc:
            last_error = exc
            if attempt < total_attempts and not emitted_token:
                time.sleep(LLM_RETRY_BACKOFF_SECONDS * attempt)
                continue
            out_queue.put({'type': 'error', 'error': GradingError('连接模型服务超时，请检查网络或服务商地址。',
                                                             code='model_connect_timeout', status_code=504)})
            return
        except requests.exceptions.ReadTimeout as exc:
            last_error = exc
            if attempt < total_attempts and not emitted_token:
                time.sleep(LLM_RETRY_BACKOFF_SECONDS * attempt)
                continue
            out_queue.put({'type': 'error', 'error': GradingError(
                f'模型响应超时，已等待{LLM_READ_TIMEOUT}秒。建议缩小答题卡截图区域、精简评分材料、稍后重试或切换更快模型。',
                code='model_read_timeout', status_code=504)})
            return
        except requests.exceptions.ConnectionError as exc:
            last_error = exc
            if attempt < total_attempts and not emitted_token:
                time.sleep(LLM_RETRY_BACKOFF_SECONDS * attempt)
                continue
            out_queue.put({'type': 'error', 'error': GradingError('连接模型服务失败，请检查网络后重试。',
                                                             code='model_connection_error', status_code=502)})
            return
        except requests.exceptions.RequestException as exc:
            last_error = exc
            out_queue.put({'type': 'error', 'error': GradingError('调用模型服务失败，请稍后重试。',
                                                             code='model_request_error', status_code=502,
                                                             detail=str(exc))})
            return
        except GradingError as exc:
            if attempt < total_attempts and not emitted_token:
                time.sleep(LLM_RETRY_BACKOFF_SECONDS * attempt)
                continue
            out_queue.put({'type': 'error', 'error': exc})
            return
        except Exception as exc:
            last_error = exc
            out_queue.put({'type': 'error', 'error': GradingError('模型流式调用失败：' + str(exc),
                                                             code='model_stream_error', status_code=502)})
            return

    out_queue.put({'type': 'error', 'error': GradingError('调用模型服务失败，请稍后重试。',
                                                     code='model_request_error', status_code=502,
                                                     detail=str(last_error) if last_error else None)})


# ---------- 分数解析 ----------

def parse_score(response_text):
    """从 LLM 响应中提取分数和结构化阅卷内容。"""
    text = (response_text or '').strip()

    def normalize_result(data):
        score = data.get('score')
        if score is None:
            return None
        return {
            'score': score,
            'max_score': data.get('max_score', 0),
            'reasoning': data.get('reasoning', ''),
            'student_answer': data.get('student_answer', ''),
            'review_analysis': data.get('review_analysis', ''),
        }

    candidates = []
    if '@@FINAL_JSON' in text:
        candidates.append(text.split('@@FINAL_JSON', 1)[1].strip())
    candidates.append(text)
    fenced_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        candidates.append(fenced_match.group(1).strip())
    if '{' in text and '}' in text:
        candidates.append(text[text.find('{'):text.rfind('}') + 1].strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                result = normalize_result(parsed)
                if result:
                    return result
        except json.JSONDecodeError:
            pass

    json_match = re.search(r'\{[^{}]*"score"[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            result = normalize_result(data)
            if result:
                return result
        except json.JSONDecodeError:
            pass

    # 尝试中文格式：得分: 8/10、分数: 8
    cn_match = re.search(r'(?:得分|分数|成绩)[:：]\s*(\d+(?:\.\d+)?)\s*/\s*(\d+)', text)
    if cn_match:
        # 尝试提取简评/评析内容
        review_analysis = ''
        ra_match = re.search(r'(?:简评|评析)[:：]\s*(.+?)(?:\n|。|$)', text)
        if ra_match:
            review_analysis = ra_match.group(1).strip()
        return {'score': float(cn_match.group(1)), 'max_score': int(cn_match.group(2)),
                'reasoning': text, 'student_answer': '', 'review_analysis': review_analysis}

    # 尝试纯数字：8/10
    num_match = re.search(r'(\d+(?:\.\d+)?)\s*/\s*(\d+)', text)
    if num_match:
        return {'score': float(num_match.group(1)), 'max_score': int(num_match.group(2)),
                'reasoning': text, 'student_answer': '', 'review_analysis': ''}

    # 尝试单独的数字
    single_match = re.search(r'(?:score|分数|得分)[^\d]*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
    if single_match:
        score = float(single_match.group(1))
        return {'score': score, 'max_score': 0, 'reasoning': text,
                'student_answer': '', 'review_analysis': ''}

    raise ValueError(f"无法从响应中解析分数: {text[:200]}")


def extract_partial_score(text):
    """从流式片段中尽早提取得分，仅用于前端展示。"""
    if not text:
        return None

    cn_match = re.search(r'(?:得分|分数|成绩)[:：]\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)', text)
    if cn_match:
        return {'score': float(cn_match.group(1)), 'max_score': float(cn_match.group(2))}

    score_match = re.search(r'"score"\s*:\s*(\d+(?:\.\d+)?)', text)
    max_match = re.search(r'"max_score"\s*:\s*(\d+(?:\.\d+)?)', text)
    if score_match and max_match:
        return {'score': float(score_match.group(1)), 'max_score': float(max_match.group(1))}

    return None


# ---------- API 端点 ----------

@app.route('/api/models', methods=['GET'])
def get_models():
    models = [
        {'id': 'doubao-seed-2-0-pro-260215', 'name': 'doubao-seed-2-0-pro-260215'}
    ]
    return jsonify(models)


@app.route('/api/test-model', methods=['POST'])
def test_model():
    data = request.json
    message = data.get('message', '')
    api_key = data.get('apiKey', '')
    model_name = data.get('modelName', 'doubao-seedance-2.0')
    provider = data.get('provider', 'doubao')

    try:
        if provider == 'local':
            return jsonify({'response': f'这是本机模型 {model_name} 的响应：\n{message}\n\n（模拟响应）'})

        if not api_key:
            return jsonify({'response': '错误：请先配置API Key'})

        if provider == 'doubao':
            api_url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        elif provider == 'deepseek':
            api_url = "https://api.deepseek.com/v1/chat/completions"
        elif provider == 'zhipu':
            api_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        else:
            return jsonify({'response': '错误：不支持的服务商'})

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "你是一个智能助手，帮助用户进行AI模型测试"},
                {"role": "user", "content": message}
            ],
            "temperature": 0.7,
            "max_tokens": 1000
        }

        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()

        if result and 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0]['message']['content']
            return jsonify({'response': content})
        else:
            return jsonify({'response': '模型响应为空'})

    except Exception as e:
        error_msg = f'调用模型失败: {str(e)}'
        return jsonify({'response': error_msg})


def build_step(steps, key, label, status='success', message='', started_at=None, extra=None):
    step = {
        'key': key,
        'label': label,
        'status': status,
        'message': message,
    }
    if started_at is not None:
        step['duration_ms'] = int((time.monotonic() - started_at) * 1000)
    if extra:
        step.update(extra)
    steps.append(step)
    return step


def analyze_card_grading(data):
    steps = []
    if not data:
        raise GradingError('请求数据为空', 'empty_request', 400, detail={'steps': steps})

    card_area = data.get('cardArea')
    standards = data.get('standards', {})
    api_key = data.get('apiKey', '')
    model_name = data.get('modelName', '')
    provider = data.get('provider', '')

    if not api_key:
        raise GradingError('请先在AI配置页面填写API Key', 'missing_api_key', 400, detail={'steps': steps})
    if not card_area:
        raise GradingError('请先框定答题卡区域', 'missing_card_area', 400, detail={'steps': steps})

    capture_started = time.monotonic()
    try:
        cx, cy, cw, ch = card_area['x'], card_area['y'], card_area['w'], card_area['h']
        log.info("截屏: x=%d, y=%d, w=%d, h=%d", cx, cy, cw, ch)
        capture = capture_screen_base64(cx, cy, cw, ch)
        image_b64 = capture['base64']
        image_mime = capture['mime_type']
        log.info("截屏成功, base64 长度: %d, mime: %s", len(image_b64), image_mime)
        build_step(steps, 'capture_card', '截取答题卡区域', 'success', '已截取答题卡区域，准备调用模型识别',
                   capture_started, {'image_meta': capture['meta']})
    except Exception as exc:
        build_step(steps, 'capture_card', '截取答题卡区域', 'error', f'截图失败：{exc}', capture_started)
        raise GradingError('截图答题卡失败，请检查答题卡标记区域。', code='capture_failed', status_code=500,
                           detail={'steps': steps}) from exc

    model_started = time.monotonic()
    try:
        log.info("调用模型: provider=%s, model=%s", provider, model_name)
        llm_result = call_llm_for_grading(provider, api_key, model_name, image_b64, standards,
                                          image_mime_type=image_mime)
        response_text = llm_result['content']
        log.info("模型响应: %s...", response_text[:200])
        build_step(
            steps,
            'model_call',
            '调用AI识别与评分模型',
            'success',
            f"模型已完成答题卡识别与评分，尝试次数：{llm_result.get('attempts', 1)}",
            model_started,
            {'attempts': llm_result.get('attempts', 1), 'model': model_name, 'provider': provider}
        )
    except GradingError as exc:
        build_step(steps, 'model_call', '调用AI识别与评分模型', 'error', exc.message, model_started)
        exc.detail = {'steps': steps}
        raise

    parse_started = time.monotonic()
    try:
        parsed = parse_score(response_text)
        score = parsed['score']
        max_score = parsed['max_score']
        reasoning = parsed.get('reasoning', '')
        student_answer = parsed.get('student_answer', '')
        review_analysis = parsed.get('review_analysis', '')
        log.info("解析分数: %s/%s", score, max_score)
        build_step(steps, 'score_result', '评分结果', 'success', f'得分：{score}/{max_score}', parse_started)
        return {
            'status': 'success',
            'score': score,
            'max_score': max_score,
            'reasoning': reasoning,
            'student_answer': student_answer,
            'review_analysis': review_analysis,
            'steps': steps
        }
    except Exception as exc:
        build_step(steps, 'score_result', '评分结果', 'error', f'无法解析模型返回的分数：{exc}', parse_started)
        raise GradingError('无法解析模型返回的分数，请重试或调整评分提示。', code='score_parse_failed',
                           status_code=422, detail={'steps': steps}) from exc


def apply_grading_result(data):
    steps = []
    if not data:
        raise GradingError('请求数据为空', 'empty_request', 400, detail={'steps': steps})

    score = data.get('score')
    score_box = data.get('scoreBox')
    submit_btn = data.get('submitBtn')

    if score is None:
        raise GradingError('缺少待填写分数。', code='missing_score', status_code=400, detail={'steps': steps})

    fill_started = time.monotonic()
    if score_box:
        try:
            sx = score_box['x'] + score_box['w'] / 2
            sy = score_box['y'] + score_box['h'] / 2
            log.info("填分: click (%d, %d), score=%s", int(sx), int(sy), score)
            auto_fill_score(sx, sy, score)
            build_step(steps, 'fill_score', '填写分数', 'success', f'已填入分数：{score}', fill_started)
        except Exception as exc:
            build_step(steps, 'fill_score', '填写分数', 'error', f'填写分数失败：{exc}', fill_started)
            raise GradingError('填写分数失败，请检查打分框标记位置。', code='fill_score_failed',
                               status_code=500, detail={'steps': steps}) from exc
    else:
        build_step(steps, 'fill_score', '填写分数', 'error', '未设置打分框位置', fill_started)
        raise GradingError('请先框定打分框位置。', code='missing_score_box', status_code=400, detail={'steps': steps})

    # 写完分数后停顿，模拟人确认分数
    log.info("填分完成，等待 %d 秒后提交...", HUMAN_SCORE_PAUSE)
    time.sleep(HUMAN_SCORE_PAUSE)

    submit_started = time.monotonic()
    if submit_btn:
        try:
            bx = submit_btn['x'] + submit_btn['w'] / 2
            by = submit_btn['y'] + submit_btn['h'] / 2
            auto_click_submit(bx, by)
            build_step(steps, 'submit', '提交结果', 'success', '已点击提交按钮', submit_started)
        except Exception as exc:
            build_step(steps, 'submit', '提交结果', 'error', f'提交失败：{exc}', submit_started)
            raise GradingError('提交失败，请检查提交按钮标记位置。', code='submit_failed', status_code=500,
                               detail={'steps': steps}) from exc
    else:
        build_step(steps, 'submit', '提交结果', 'error', '未设置提交按钮位置', submit_started)
        raise GradingError('请先框定提交按钮位置。', code='missing_submit_button', status_code=400, detail={'steps': steps})

    return {'status': 'success', 'steps': steps}


def grading_error_response(exc):
    steps = []
    if isinstance(exc.detail, dict):
        steps = exc.detail.get('steps', []) or []
    return jsonify({'status': 'error', 'code': exc.code, 'message': exc.message, 'steps': steps}), exc.status_code


def ndjson_event(event_type, **payload):
    data = {'type': event_type}
    data.update(payload)
    return json.dumps(data, ensure_ascii=False) + '\n'


def stream_analyze_card_grading(data):
    request_started = time.monotonic()
    if not data:
        yield ndjson_event('error', code='empty_request', message='请求数据为空')
        return

    card_area = data.get('cardArea')
    standards = data.get('standards', {})
    api_key = data.get('apiKey', '')
    model_name = data.get('modelName', '')
    provider = data.get('provider', '')
    ocr_api_key = data.get('ocrApiKey', '') or ''

    if not api_key:
        yield ndjson_event('error', code='missing_api_key', message='请先在AI配置页面填写API Key')
        return
    if not ocr_api_key:
        yield ndjson_event('error', code='missing_ocr_api_key',
                           message='请先在AI配置页面填写智谱 OCR API Key')
        return
    if not card_area:
        yield ndjson_event('error', code='missing_card_area', message='请先框定答题卡区域')
        return

    yield ndjson_event('status', message='已收到评分请求，正在准备截图...')

    # ── 截图 + 预处理 ──
    yield ndjson_event('status', message='正在截取答题卡区域...')
    capture_started = time.monotonic()
    try:
        cx, cy, cw, ch = card_area['x'], card_area['y'], card_area['w'], card_area['h']
        log.info('截屏: x=%d, y=%d, w=%d, h=%d', cx, cy, cw, ch)
        capture = capture_screen_base64(cx, cy, cw, ch)
        image_b64 = capture['base64']
        image_mime = capture['mime_type']
        image_meta = capture['meta']
        capture_ms = int((time.monotonic() - capture_started) * 1000)
        log.info('截屏成功, base64 长度: %d, mime: %s, 耗时: %d ms', len(image_b64), image_mime, capture_ms)
        yield ndjson_event('timing', key='capture', label='截图压缩', duration_ms=capture_ms,
                           input_bytes=image_meta.get('input_bytes'),
                           output_bytes=image_meta.get('output_bytes'),
                           resized=image_meta.get('resized'))
    except Exception as exc:
        yield ndjson_event('error', code='capture_failed', message=f'截图答题卡失败：{exc}')
        return

    # ── 智谱 OCR（手写识别） ──
    yield ndjson_event('status', message='正在调用智谱 OCR 识别手写文字...')
    ocr_started = time.monotonic()
    try:
        # base64 解码回 bytes（capture 已经是预处理后的 jpeg/png 字节）
        image_bytes = base64.b64decode(image_b64)
        ext = 'jpg' if image_mime == 'image/jpeg' else 'png'
        ocr_result = call_handwriting_ocr(
            ocr_api_key,
            image_bytes,
            mime_type=image_mime,
            filename=f'card.{ext}',
        )
        ocr_text = ocr_result['text']
        ocr_ms = int((time.monotonic() - ocr_started) * 1000)
        log.info('OCR 完成, 字数=%d, 耗时=%d ms', len(ocr_text), ocr_ms)
        yield ndjson_event('timing', key='ocr', label='OCR识别', duration_ms=ocr_ms,
                           words_count=ocr_result['words_count'])
        # 把 OCR 文本一次性推给前端，前端塞到「学生作答」区
        yield ndjson_event('ocr_text', text=ocr_text, words_count=ocr_result['words_count'])
        if not ocr_text.strip():
            yield ndjson_event('error', code='ocr_empty_result',
                               message='OCR 未识别到手写作答，请确认框选范围或调整图片')
            return
    except OCRError as exc:
        log.warning('OCR 失败: %s', exc.message)
        yield ndjson_event('error', code=exc.code, message=exc.message)
        return
    except Exception as exc:
        log.exception('OCR 调用异常')
        yield ndjson_event('error', code='ocr_failed', message=f'OCR 调用失败：{exc}')
        return

    # ── AI 评分（流式，纯文本路径） ──
    yield ndjson_event('status', message='OCR 完成，正在调用评分模型...')
    model_started = time.monotonic()
    model_queue = queue.Queue()
    worker = threading.Thread(
        target=stream_llm_for_grading,
        args=(provider, api_key, model_name, image_b64, standards, model_queue),
        kwargs={'image_mime_type': image_mime, 'ocr_text': ocr_text},
        daemon=True
    )
    worker.start()
    yield ndjson_event('status', message='AI请求已发起，等待模型首段输出...', elapsed_ms=0)

    full_text = ''
    llm_meta = {}
    partial_score_sent = False
    first_byte_seen = False
    first_byte_ms = None
    while True:
        try:
            item = model_queue.get(timeout=1)
        except queue.Empty:
            elapsed_ms = int((time.monotonic() - model_started) * 1000)
            # 首包超时熔断：模型尚未吐出任何内容
            if not first_byte_seen and elapsed_ms >= LLM_FIRST_BYTE_TIMEOUT * 1000:
                log.warning('首包超时 %d ms（阈值 %d ms），熔断', elapsed_ms, LLM_FIRST_BYTE_TIMEOUT * 1000)
                yield ndjson_event('error', code='model_first_byte_timeout',
                                   message=f'模型 {LLM_FIRST_BYTE_TIMEOUT}s 内未返回内容，已熔断')
                return
            yield ndjson_event('status',
                               message=f'AI正在识别评分，已等待 {elapsed_ms // 1000} 秒...',
                               elapsed_ms=elapsed_ms)
            continue

        item_type = item.get('type')
        if item_type == 'status':
            yield ndjson_event('status', message=item.get('message', '模型请求处理中...'),
                               elapsed_ms=int((time.monotonic() - model_started) * 1000))
        elif item_type == 'token':
            token_content = item.get('content', '')
            if not first_byte_seen:
                first_byte_seen = True
                first_byte_ms = int((time.monotonic() - model_started) * 1000)
                log.info('首包到达, 耗时 %d ms', first_byte_ms)
                yield ndjson_event('timing', key='model_first_byte', label='首响', duration_ms=first_byte_ms)
            full_text += token_content
            yield ndjson_event('token', content=token_content)
            if not partial_score_sent:
                partial_score = extract_partial_score(full_text)
                if partial_score:
                    partial_score_sent = True
                    yield ndjson_event('partial_score', **partial_score)
        elif item_type == 'reasoning':
            if not first_byte_seen:
                first_byte_seen = True
                first_byte_ms = int((time.monotonic() - model_started) * 1000)
                log.info('首包到达（reasoning）, 耗时 %d ms', first_byte_ms)
                yield ndjson_event('timing', key='model_first_byte', label='首响', duration_ms=first_byte_ms)
            yield ndjson_event('reasoning', content=item.get('content', ''))
        elif item_type == 'done':
            full_text = item.get('content', '')
            llm_meta = item
            break
        elif item_type == 'error':
            exc_err = item.get('error')
            if not isinstance(exc_err, GradingError):
                exc_err = GradingError(str(exc_err or '模型流式调用失败'), code='model_stream_error', status_code=502)
            yield ndjson_event('error', code=exc_err.code, message=exc_err.message)
            return

    model_ms = int((time.monotonic() - model_started) * 1000)
    log.info('模型流式输出完成, 耗时 %d ms, 文本长度 %d', llm_meta.get('duration_ms', model_ms), len(full_text))
    yield ndjson_event('timing', key='model_call', label='评分', duration_ms=model_ms)

    # ── 解析结果 ──
    parse_started = time.monotonic()
    try:
        parsed = parse_score(full_text)
        score = parsed['score']
        max_score = parsed['max_score']
        reasoning = parsed.get('reasoning', '')
        # 学生作答以 OCR 文本为准（覆盖模型可能的瞎写）
        student_answer = ocr_text
        review_analysis = parsed.get('review_analysis', '')
        parse_ms = int((time.monotonic() - parse_started) * 1000)
        total_ms = int((time.monotonic() - request_started) * 1000)
        log.info('解析分数: %s/%s, parse=%d ms, total=%d ms', score, max_score, parse_ms, total_ms)
        yield ndjson_event('timing', key='parse', label='解析', duration_ms=parse_ms)

        timings = {
            'capture_ms': capture_ms,
            'ocr_ms': ocr_ms,
            'model_first_byte_ms': first_byte_ms,
            'model_ms': model_ms,
            'parse_ms': parse_ms,
            'total_ms': total_ms,
            'input_bytes': image_meta.get('input_bytes'),
            'output_bytes': image_meta.get('output_bytes'),
        }

        provider_label_map = {
            'zhipu': '智谱',
            'doubao': '豆包',
            'deepseek': 'DeepSeek',
        }
        provider_label = '%s-%s' % (provider_label_map.get(provider, provider), model_name)

        yield ndjson_event('final', result={
            'status': 'success',
            'score': score,
            'max_score': max_score,
            'reasoning': reasoning,
            'student_answer': student_answer,
            'review_analysis': review_analysis,
            'full_text': full_text,
            'ocr_text': ocr_text,
            'provider_label': provider_label,
            'ocr_label': '智谱-GLM-OCR',
            'timings': timings,
        })
    except Exception as exc:
        yield ndjson_event('error', code='score_parse_failed',
                           message=f'无法解析模型返回的分数：{exc}')


@app.route('/api/grade/analyze-stream', methods=['POST'])
def grade_analyze_stream():
    data = request.get_json(silent=True) or {}
    return Response(
        stream_with_context(stream_analyze_card_grading(data)),
        content_type='application/x-ndjson; charset=utf-8',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


@app.route('/api/grade/analyze', methods=['POST'])
def grade_analyze():
    try:
        return jsonify(analyze_card_grading(request.json))
    except GradingError as exc:
        return grading_error_response(exc)
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'status': 'error', 'code': 'unexpected_error', 'message': '批改失败：' + str(exc), 'steps': []}), 500


@app.route('/api/grade/apply', methods=['POST'])
def grade_apply():
    try:
        return jsonify(apply_grading_result(request.json))
    except GradingError as exc:
        return grading_error_response(exc)
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'status': 'error', 'code': 'unexpected_error', 'message': '填写或提交失败：' + str(exc), 'steps': []}), 500


@app.route('/api/grade', methods=['POST'])
def grade_papers():
    try:
        data = request.json
        analyze_result = analyze_card_grading(data)
        apply_data = {
            'score': analyze_result['score'],
            'scoreBox': data.get('scoreBox') if data else None,
            'submitBtn': data.get('submitBtn') if data else None,
        }
        apply_result = apply_grading_result(apply_data)
        analyze_result['steps'] = analyze_result.get('steps', []) + apply_result.get('steps', [])
        return jsonify(analyze_result)
    except GradingError as exc:
        return grading_error_response(exc)
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'status': 'error', 'code': 'unexpected_error', 'message': '批改失败：' + str(exc), 'steps': []}), 500


# ---------- 预设管理 ----------

def ensure_presets_file():
    if not os.path.exists(PRESETS_FILE):
        secure_write_json(PRESETS_FILE, {'presets': [], 'last_preset': None})
    else:
        # 迁移旧的明文 presets.json
        try:
            with open(PRESETS_FILE, 'r', encoding='utf-8') as f:
                json.load(f)
            # 文件是明文 JSON，迁移到加密格式
            with open(PRESETS_FILE, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
            secure_write_json(PRESETS_FILE, old_data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass  # 已经是加密格式


@app.route('/api/save-preset', methods=['POST'])
def save_preset():
    try:
        ensure_presets_file()
        data = request.json
        api_key = data.get('apiKey', '')
        model_name = data.get('modelName', '')
        provider = data.get('provider', '')
        ocr_api_key = data.get('ocrApiKey', '')

        if not api_key:
            return jsonify({'status': 'error', 'message': 'API Key不能为空'})

        presets_data = secure_read_json(PRESETS_FILE)
        if presets_data is None:
            presets_data = {'presets': [], 'last_preset': None}

        new_preset = {
            'apiKey': api_key,
            'modelName': model_name,
            'provider': provider,
            'ocrApiKey': ocr_api_key,
            'timestamp': datetime.datetime.now().isoformat()
        }

        presets_data['presets'].append(new_preset)
        presets_data['last_preset'] = new_preset

        secure_write_json(PRESETS_FILE, presets_data)

        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/get-presets', methods=['GET'])
def get_presets():
    try:
        ensure_presets_file()
        presets_data = secure_read_json(PRESETS_FILE)
        if presets_data is None:
            presets_data = {'presets': []}
        return jsonify({'status': 'success', 'presets': presets_data.get('presets', [])})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/get-last-preset', methods=['GET'])
def get_last_preset():
    try:
        ensure_presets_file()
        presets_data = secure_read_json(PRESETS_FILE)
        if presets_data is None:
            presets_data = {'last_preset': None}
        return jsonify({'status': 'success', 'preset': presets_data.get('last_preset')})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/delete-preset', methods=['POST'])
def delete_preset():
    try:
        ensure_presets_file()
        data = request.get_json(silent=True) or {}
        index = data.get('index')
        presets_data = secure_read_json(PRESETS_FILE)
        if presets_data is None:
            presets_data = {'presets': [], 'last_preset': None}
        presets = presets_data.get('presets', [])
        if index is None or index < 0 or index >= len(presets):
            return jsonify({'status': 'error', 'message': '无效的预设索引'})
        presets.pop(index)
        presets_data['presets'] = presets
        # 如果删除的是 last_preset，清除它
        last = presets_data.get('last_preset')
        if last and last not in presets:
            presets_data['last_preset'] = presets[-1] if presets else None
        secure_write_json(PRESETS_FILE, presets_data)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


# ---------- 激活管理 ----------

@app.route('/api/hwid', methods=['GET'])
def get_hwid():
    return jsonify({'hwid': generate_hwid()})


@app.route('/api/activate', methods=['POST'])
def activate():
    data = request.json
    license_key = data.get('licenseKey', '').strip()
    if not license_key:
        return jsonify({'status': 'error', 'message': '请输入激活码'})

    valid, result = validate_license_key(license_key)
    if valid:
        store_license(license_key)
        global ACTIVATED
        ACTIVATED = True
        return jsonify({'status': 'success', 'message': '激活成功！请重启应用。'})
    else:
        return jsonify({'status': 'error', 'message': result})


# ---------- 激活页面 ----------

@app.route('/activate')
def serve_activation():
    return ACTIVATION_HTML


if __name__ == '__main__':
    import os as _os
    port = int(_os.environ.get('FLASK_PORT', 5000))
    debug = _os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='127.0.0.1', port=port, debug=debug, use_reloader=False, threaded=True)
