from flask import Flask, request, jsonify, send_from_directory
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
    """截屏并返回 base64 字符串"""
    png_bytes = capture_screen(x, y, w, h)
    return base64.b64encode(png_bytes).decode('utf-8')


# ---------- 桌面自动化 ----------

def auto_fill_score(x, y, score):
    """在指定屏幕位置填入分数"""
    import pyautogui
    pyautogui.click(int(x), int(y))
    pyautogui.sleep(0.3)
    pyautogui.hotkey('ctrl', 'a')
    pyautogui.sleep(0.1)
    pyautogui.typewrite(str(score), interval=0.05)


def auto_click_submit(x, y):
    """点击提交按钮"""
    import pyautogui
    pyautogui.click(int(x), int(y))


# ---------- 多模态 LLM 调用 ----------

LLM_CONNECT_TIMEOUT = 10
LLM_READ_TIMEOUT = 180
LLM_MAX_RETRIES = 1
LLM_RETRY_BACKOFF_SECONDS = 2
LLM_MAX_TOKENS = 500


class GradingError(Exception):
    def __init__(self, message, code='grading_error', status_code=500, detail=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.detail = detail


GRADING_SYSTEM_PROMPT = """你是一位专业、严格、稳定的阅卷老师。你的任务是根据用户提供的答题卡截图、题目材料、参考答案、评价示例和评分要求，对截图中的学生作答进行评分。

评分规则：
1. 只评价答题卡截图中能看清的学生作答内容，不要臆测看不清或截图外的内容。
2. 必须优先遵循“评分要求”；如评分要求与参考答案冲突，以评分要求为准。
3. 参考答案用于判断核心要点，评价示例用于校准给分尺度，题目材料用于理解题意。
4. 如果学生答案部分正确，应按评分要求给出合理的部分分。
5. 如果无法识别学生作答，score 必须为 0，并在 reasoning 中说明无法识别。
6. score 只能是数字；如果评分要求中能判断满分，max_score 填该满分，否则填 0。
7. 需要按“学生作答、阅卷评析、成绩得分”三个步骤组织结果。
8. 只能返回一个 JSON 对象，不要返回 Markdown、代码块或额外解释。

返回格式：
{"student_answer": "<识别出的学生作答>", "review_analysis": "<阅卷评析>", "score": <得分数字>, "max_score": <满分数字>, "reasoning": "<简短说明扣分/给分依据>"}"""


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


def build_grading_messages(image_base64, standards):
    """构建多模态 grading prompt"""
    parts = []

    # 图片
    parts.append({
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{image_base64}"}
    })

    material = html_to_text(standards.get('material', ''))
    answer = html_to_text(standards.get('answer', ''))
    example = html_to_text(standards.get('example', ''))
    requirement = html_to_text(standards.get('requirement', ''))

    # 文本 prompt
    text_parts = [
        "请对随消息附带的答题卡截图进行评分。",
        "答题卡截图中是学生作答内容；下面是评分依据。",
    ]

    if material:
        text_parts.append(f"【题目材料】\n{material}")
    if answer:
        text_parts.append(f"【参考答案】\n{answer}")
    if example:
        text_parts.append(f"【评价示例】\n{example}")
    if requirement:
        text_parts.append(f"【评分要求】\n{requirement}")

    text_parts.append(
        "请严格根据以上依据和截图中的学生答案评分，并按学生作答、阅卷评析、成绩得分三个步骤返回。只返回 JSON："
        "{\"student_answer\": \"<识别出的学生作答>\", "
        "\"review_analysis\": \"<阅卷评析>\", "
        "\"score\": <得分数字>, \"max_score\": <满分数字>, \"reasoning\": \"<简短依据>\"}"
    )

    parts.append({"type": "text", "text": "\n\n".join(text_parts)})

    return [
        {"role": "system", "content": GRADING_SYSTEM_PROMPT},
        {"role": "user", "content": parts}
    ]


def get_provider_api_url(provider):
    if provider == 'doubao':
        return "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    if provider == 'deepseek':
        return "https://api.deepseek.com/v1/chat/completions"
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


def call_llm_for_grading(provider, api_key, model_name, image_base64, standards):
    """调用大模型进行批改，返回响应文本和调用元数据。"""
    api_url = get_provider_api_url(provider)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    payload = {
        "model": model_name,
        "messages": build_grading_messages(image_base64, standards),
        "temperature": 0.3,
        "max_tokens": LLM_MAX_TOKENS
    }

    total_attempts = LLM_MAX_RETRIES + 1
    started = time.monotonic()
    last_error = None

    for attempt in range(1, total_attempts + 1):
        try:
            print(f"[Grade] 模型请求 attempt={attempt}/{total_attempts}, timeout={LLM_READ_TIMEOUT}s")
            response = requests.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=(LLM_CONNECT_TIMEOUT, LLM_READ_TIMEOUT)
            )

            if response.status_code in (408, 429, 500, 502, 503, 504) and attempt < total_attempts:
                print(f"[Grade] 模型服务返回 {response.status_code}，准备重试")
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


# ---------- 分数解析 ----------

def parse_score(response_text):
    """从 LLM 响应中提取分数"""
    # 尝试 JSON 解析
    json_match = re.search(r'\{[^{}]*"score"[^{}]*\}', response_text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            score = data.get('score')
            max_score = data.get('max_score', 0)
            reasoning = data.get('reasoning', '')
            student_answer = data.get('student_answer', '')
            review_analysis = data.get('review_analysis', '')
            if score is not None:
                return {
                    'score': score,
                    'max_score': max_score,
                    'reasoning': reasoning,
                    'student_answer': student_answer,
                    'review_analysis': review_analysis,
                }
        except json.JSONDecodeError:
            pass

    # 尝试中文格式：得分: 8/10、分数: 8
    cn_match = re.search(r'(?:得分|分数|成绩)[:：]\s*(\d+(?:\.\d+)?)\s*/\s*(\d+)', response_text)
    if cn_match:
        return {'score': float(cn_match.group(1)), 'max_score': int(cn_match.group(2)),
                'reasoning': response_text}

    # 尝试纯数字：8/10
    num_match = re.search(r'(\d+(?:\.\d+)?)\s*/\s*(\d+)', response_text)
    if num_match:
        return {'score': float(num_match.group(1)), 'max_score': int(num_match.group(2)),
                'reasoning': response_text}

    # 尝试单独的数字
    single_match = re.search(r'(?:score|分数|得分)[^\d]*(\d+(?:\.\d+)?)', response_text, re.IGNORECASE)
    if single_match:
        score = float(single_match.group(1))
        return {'score': score, 'max_score': 0, 'reasoning': response_text}

    raise ValueError(f"无法从响应中解析分数: {response_text[:200]}")


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


@app.route('/api/grade', methods=['POST'])
def grade_papers():
    data = request.json
    steps = []

    def add_step(key, label, status='success', message='', started_at=None, extra=None):
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

    def error_response(message, code='grading_error', status_code=500):
        return jsonify({'status': 'error', 'code': code, 'message': message, 'steps': steps}), status_code

    if not data:
        return error_response('请求数据为空', 'empty_request', 400)

    card_area = data.get('cardArea')
    score_box = data.get('scoreBox')
    submit_btn = data.get('submitBtn')
    standards = data.get('standards', {})
    api_key = data.get('apiKey', '')
    model_name = data.get('modelName', '')
    provider = data.get('provider', '')

    # 验证
    if not api_key:
        return error_response('请先在AI配置页面填写API Key', 'missing_api_key', 400)
    if not card_area:
        return error_response('请先框定答题卡区域', 'missing_card_area', 400)

    try:
        # 1. 截屏
        capture_started = time.monotonic()
        try:
            cx, cy, cw, ch = card_area['x'], card_area['y'], card_area['w'], card_area['h']
            print(f"[Grade] 截屏: x={cx}, y={cy}, w={cw}, h={ch}")
            image_b64 = capture_screen_base64(cx, cy, cw, ch)
            print(f"[Grade] 截屏成功, base64 长度: {len(image_b64)}")
            add_step('scan_card', '扫描答题卡', 'success', '答题卡区域截图完成，已发送给大模型识别', capture_started)
        except Exception as exc:
            add_step('scan_card', '扫描答题卡', 'error', f'截图失败：{exc}', capture_started)
            raise GradingError('截图答题卡失败，请检查答题卡标记区域。', code='capture_failed', status_code=500) from exc

        # 2. 调用 LLM 批改
        model_started = time.monotonic()
        try:
            print(f"[Grade] 调用模型: provider={provider}, model={model_name}")
            llm_result = call_llm_for_grading(provider, api_key, model_name, image_b64, standards)
            response_text = llm_result['content']
            print(f"[Grade] 模型响应: {response_text[:200]}")
            add_step(
                'model_call',
                '调用AI模型',
                'success',
                f"模型返回成功，尝试次数：{llm_result.get('attempts', 1)}",
                model_started,
                {'attempts': llm_result.get('attempts', 1), 'model': model_name, 'provider': provider}
            )
        except GradingError as exc:
            add_step('model_call', '调用AI模型', 'error', exc.message, model_started)
            raise

        # 3. 解析分数
        parse_started = time.monotonic()
        try:
            result = parse_score(response_text)
            score = result['score']
            max_score = result['max_score']
            reasoning = result.get('reasoning', '')
            student_answer = result.get('student_answer', '')
            review_analysis = result.get('review_analysis', '')
            print(f"[Grade] 解析分数: {score}/{max_score}")
            add_step('student_answer', '学生作答', 'success', student_answer or '模型未返回可识别的学生作答', parse_started)
            add_step('review_analysis', '阅卷评析', 'success', review_analysis or reasoning or '模型未返回阅卷评析', parse_started)
            add_step('score_result', '成绩得分', 'success', f'得分：{score}/{max_score}', parse_started)
        except Exception as exc:
            add_step('score_result', '成绩得分', 'error', f'无法解析模型返回的分数：{exc}', parse_started)
            raise GradingError('无法解析模型返回的分数，请重试或调整评分提示。', code='score_parse_failed',
                               status_code=422) from exc

        # 4. 桌面自动化 - 填分
        fill_started = time.monotonic()
        if score_box:
            try:
                sx = score_box['x'] + score_box['w'] / 2
                sy = score_box['y'] + score_box['h'] / 2
                print(f"[Grade] 填分: click ({sx}, {sy}), score={score}")
                auto_fill_score(sx, sy, score)
                add_step('fill_score', '填写分数', 'success', f'已填入分数：{score}', fill_started)
            except Exception as exc:
                add_step('fill_score', '填写分数', 'error', f'填写分数失败：{exc}', fill_started)
                raise GradingError('填写分数失败，请检查打分框标记位置。', code='fill_score_failed',
                                   status_code=500) from exc
        else:
            add_step('fill_score', '填写分数', 'error', '未设置打分框位置', fill_started)
            raise GradingError('请先框定打分框位置。', code='missing_score_box', status_code=400)

        # 5. 桌面自动化 - 提交
        submit_started = time.monotonic()
        if submit_btn:
            try:
                bx = submit_btn['x'] + submit_btn['w'] / 2
                by = submit_btn['y'] + submit_btn['h'] / 2
                print(f"[Grade] 提交: click ({bx}, {by})")
                auto_click_submit(bx, by)
                add_step('submit', '提交结果', 'success', '已点击提交按钮', submit_started)
            except Exception as exc:
                add_step('submit', '提交结果', 'error', f'提交失败：{exc}', submit_started)
                raise GradingError('提交失败，请检查提交按钮标记位置。', code='submit_failed', status_code=500) from exc
        else:
            add_step('submit', '提交结果', 'error', '未设置提交按钮位置', submit_started)
            raise GradingError('请先框定提交按钮位置。', code='missing_submit_button', status_code=400)

        return jsonify({
            'status': 'success',
            'score': score,
            'max_score': max_score,
            'reasoning': reasoning,
            'student_answer': student_answer,
            'review_analysis': review_analysis,
            'steps': steps
        })

    except GradingError as e:
        return error_response(e.message, e.code, e.status_code)
    except Exception as e:
        traceback.print_exc()
        return error_response('批改失败：' + str(e), 'unexpected_error', 500)


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

        if not api_key:
            return jsonify({'status': 'error', 'message': 'API Key不能为空'})

        presets_data = secure_read_json(PRESETS_FILE)
        if presets_data is None:
            presets_data = {'presets': [], 'last_preset': None}

        new_preset = {
            'apiKey': api_key,
            'modelName': model_name,
            'provider': provider,
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
    app.run(host='127.0.0.1', port=port, debug=debug, use_reloader=False)
