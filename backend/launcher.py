"""好帮手AI阅卷 - 桌面启动入口。PyInstaller 打包时以此文件为入口。"""
import sys
import os
import socket
import ctypes
from ctypes import wintypes
import threading
import time
import logging
import queue
import json
import webview

# 最先执行完整性校验
import integrity  # noqa: E402

# 确保当前目录在 sys.path 中（PyInstaller onefile 模式需要）
if getattr(sys, 'frozen', False):
    sys.path.insert(0, sys._MEIPASS)
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.getLogger('werkzeug').setLevel(logging.WARNING)

# ---------- 标记常量 ----------

# 三色尽量拉开视觉差异（红/蓝/绿），避免粉与紫难分辨
MARKER_COLORS_HEX = {
    'card':   '#e53935',
    'score':  '#1e88e5',
    'submit': '#43a047',
}

# 上次标记框位置/大小的持久化文件（统一放 %APPDATA%\AI_Grader，与预设同目录）
try:
    from paths import data_file as _data_file
except Exception:
    _data_file = None

if _data_file is not None:
    MARKER_STATE_FILE = _data_file('marker_state.json')
else:
    # 兜底：paths 模块不可用时退回 exe 同级目录
    if getattr(sys, 'frozen', False):
        _DATA_DIR = os.path.dirname(sys.executable)
    else:
        _DATA_DIR = os.path.dirname(os.path.abspath(__file__))
    MARKER_STATE_FILE = os.path.join(_DATA_DIR, 'marker_state.json')


def _load_marker_state():
    """读取上次保存的标记框位置；文件缺失/损坏时返回空 dict。"""
    try:
        with open(MARKER_STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_marker_rect(mtype, rect):
    """记住某个标记框最新的位置与大小（原子写入，失败不影响批改）。"""
    try:
        data = _load_marker_state()
        data[mtype] = {
            'x': int(rect['x']), 'y': int(rect['y']),
            'w': int(rect['w']), 'h': int(rect['h']),
        }
        tmp = MARKER_STATE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, MARKER_STATE_FILE)
    except Exception:
        try:
            log.warning('保存标记框位置失败: %s', mtype, exc_info=True)
        except Exception:
            pass

MARKER_TRANSPARENT_COLOR = '#010203'

MARKER_LABELS = {
    'card':   '答题卡区域',
    'score':  '打分框位置',
    'submit': '提交按钮位置',
}

MARKER_SIZES = {
    'card':   (400, 300),
    'score':  (225, 53),
    'submit': (225, 53),
}

MARKER_ORDER = ('card', 'score', 'submit')


def _shade_color(hex_color, ratio):
    """颜色微调：ratio<0 向黑过渡，ratio>0 向白过渡，用于扫描线渐变取色。"""
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if ratio >= 0:
        r = int(r + (255 - r) * ratio)
        g = int(g + (255 - g) * ratio)
        b = int(b + (255 - b) * ratio)
    else:
        f = 1.0 + ratio
        r, g, b = int(r * f), int(g * f), int(b * f)
    return '#%02x%02x%02x' % (min(r, 255), min(g, 255), min(b, 255))


def _scan_band_palette(base):
    """由标记颜色生成对称的渐变光带（深→基色→近白→基色→深），保证与标记线/标记按钮同色系。"""
    stops = (-0.65, -0.40, -0.15, 0.30, 0.88, 0.30, -0.15, -0.40, -0.65)
    heights = (1, 2, 3, 4, 5, 4, 3, 2, 1)
    return [(_shade_color(base, s), h) for s, h in zip(stops, heights)]

# ---------- 标记线程通信 ----------

_marker_queue = queue.Queue()  # 主线程 → tkinter 线程
log = logging.getLogger('ai_grade')  # 与 app.py 同一日志通道


class TkMarker:
    """由四条独立细窗口组成的空心虚线标记框，内部透明热区用于拖动。"""

    _BORDER = 6
    _RESIZE_MARGIN = 24
    _MIN_W = 100
    _MIN_H = 50

    _RESIZE_CURSORS = {
        'n':  'sb_v_double_arrow',
        's':  'sb_v_double_arrow',
        'e':  'sb_h_double_arrow',
        'w':  'sb_h_double_arrow',
        'ne': 'top_right_corner',
        'nw': 'top_left_corner',
        'se': 'bottom_right_corner',
        'sw': 'bottom_left_corner',
        'move': 'fleur',
    }

    def __init__(self, root, mtype):
        import tkinter as tk
        self._mtype = mtype
        self._color = MARKER_COLORS_HEX[mtype]
        self._root = root
        self._visible = False
        self._rect = {'x': 0, 'y': 0, 'w': MARKER_SIZES[mtype][0], 'h': MARKER_SIZES[mtype][1]}
        self._drag_start = None  # (mode, root_x, root_y, x, y, w, h)
        self._wins = {}
        self._canvases = {}
        self._line_ids = {}

        self._drag_win = tk.Toplevel(root)
        self._drag_win.overrideredirect(True)
        self._drag_win.attributes('-topmost', True)
        self._drag_win.attributes('-toolwindow', True)
        self._drag_win.attributes('-alpha', 0.01)
        self._drag_win.configure(bg=MARKER_TRANSPARENT_COLOR, cursor='fleur')
        self._drag_win.withdraw()
        self._drag_win.bind('<Button-1>', lambda e: self._on_press(e, 'inner'))
        self._drag_win.bind('<B1-Motion>', self._on_move)
        self._drag_win.bind('<ButtonRelease-1>', self._on_release)

        for part in ('top', 'bottom', 'left', 'right'):
            win = tk.Toplevel(root)
            win.overrideredirect(True)
            win.attributes('-topmost', True)
            win.attributes('-toolwindow', True)
            win.configure(bg=MARKER_TRANSPARENT_COLOR)
            canvas = tk.Canvas(
                win,
                bg=MARKER_TRANSPARENT_COLOR,
                highlightthickness=0,
                bd=0,
                cursor='fleur'
            )
            canvas.pack(fill='both', expand=True)
            line_id = canvas.create_line(0, 0, 1, 1, fill=self._color, width=5)
            win.withdraw()

            self._wins[part] = win
            self._canvases[part] = canvas
            self._line_ids[part] = line_id

            for target in (win, canvas):
                target.bind('<Button-1>', lambda e, p=part: self._on_press(e, p))
                target.bind('<B1-Motion>', self._on_move)
                target.bind('<ButtonRelease-1>', self._on_release)
                target.bind('<Motion>', lambda e, p=part: self._on_motion(e, p))
                target.bind('<Leave>', self._on_leave)

    def _mode_for_part(self, event, part):
        x, y, w, h = self._rect['x'], self._rect['y'], self._rect['w'], self._rect['h']
        m = self._RESIZE_MARGIN
        rx = event.x_root - x
        ry = event.y_root - y

        if part == 'top':
            if rx <= m:
                return 'nw'
            if rx >= w - m:
                return 'ne'
            return 'move'
        if part == 'bottom':
            if rx <= m:
                return 'sw'
            if rx >= w - m:
                return 'se'
            return 'move'
        if part == 'left':
            if ry <= m:
                return 'nw'
            if ry >= h - m:
                return 'sw'
            return 'move'
        if part == 'right':
            if ry <= m:
                return 'ne'
            if ry >= h - m:
                return 'se'
            return 'move'
        if part == 'inner':
            return 'move'
        return 'move'

    def _on_motion(self, event, part):
        cursor = self._RESIZE_CURSORS.get(self._mode_for_part(event, part), 'fleur')
        for win in self._wins.values():
            win.configure(cursor=cursor)
        for canvas in self._canvases.values():
            canvas.configure(cursor=cursor)

    def _on_leave(self, event):
        for win in self._wins.values():
            win.configure(cursor='fleur')
        for canvas in self._canvases.values():
            canvas.configure(cursor='fleur')

    def _on_press(self, event, part):
        self._drag_start = (
            self._mode_for_part(event, part),
            event.x_root,
            event.y_root,
            self._rect['x'],
            self._rect['y'],
            self._rect['w'],
            self._rect['h'],
        )

    def _on_move(self, event):
        if not self._drag_start:
            return
        mode, sx, sy, x, y, w, h = self._drag_start
        dx = event.x_root - sx
        dy = event.y_root - sy

        new_x, new_y, new_w, new_h = x, y, w, h
        if mode == 'move':
            new_x = x + dx
            new_y = y + dy
        else:
            if 'e' in mode:
                new_w = max(self._MIN_W, w + dx)
            if 'w' in mode:
                new_w = max(self._MIN_W, w - dx)
                new_x = x + w - new_w
            if 's' in mode:
                new_h = max(self._MIN_H, h + dy)
            if 'n' in mode:
                new_h = max(self._MIN_H, h - dy)
                new_y = y + h - new_h

        self._rect = {'x': int(new_x), 'y': int(new_y), 'w': int(new_w), 'h': int(new_h)}
        self._layout()

    def _on_release(self, event):
        self._drag_start = None
        # 用户拖动/缩放结束后记住位置与大小，下次启动直接复用
        _save_marker_rect(self._mtype, self._rect)

    def _layout(self):
        x, y, w, h = self._rect['x'], self._rect['y'], self._rect['w'], self._rect['h']
        b = self._BORDER

        inner_w = max(1, w - b * 2)
        inner_h = max(1, h - b * 2)
        self._drag_win.geometry(f'{inner_w}x{inner_h}+{x + b}+{y + b}')

        self._wins['top'].geometry(f'{w}x{b}+{x}+{y}')
        self._wins['bottom'].geometry(f'{w}x{b}+{x}+{y + h - b}')
        self._wins['left'].geometry(f'{b}x{h}+{x}+{y}')
        self._wins['right'].geometry(f'{b}x{h}+{x + w - b}+{y}')

        self._canvases['top'].coords(self._line_ids['top'], 0, b // 2, w, b // 2)
        self._canvases['bottom'].coords(self._line_ids['bottom'], 0, b // 2, w, b // 2)
        self._canvases['left'].coords(self._line_ids['left'], b // 2, 0, b // 2, h)
        self._canvases['right'].coords(self._line_ids['right'], b // 2, 0, b // 2, h)

    # ---- 公共接口（通过 queue 在 tkinter 线程中调用） ----

    def get_rect(self):
        return dict(self._rect)

    def is_visible(self):
        return self._visible

    def _show(self, x, y, w, h):
        self._rect = {'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h)}
        self._layout()
        self._drag_win.deiconify()
        self._drag_win.lift()
        for win in self._wins.values():
            win.deiconify()
            win.lift()
        self._visible = True

    def _hide(self):
        self._drag_win.withdraw()
        for win in self._wins.values():
            win.withdraw()
        self._visible = False

    def _destroy(self):
        self._drag_win.destroy()
        for win in list(self._wins.values()):
            win.destroy()
        self._wins.clear()
        self._canvases.clear()
        self._line_ids.clear()


class TkScanLine:
    """答题卡区域扫描线动画。支持单次扫描和循环扫描两种模式。

    增强：
    - 渐变光带：9 层窗口叠加（深→标记色→近白→标记色→深）模拟渐变扫描线
    - 同色系：取色跟随答题卡区域标记颜色，与标记线、标记按钮保持一致
    - 正弦缓动：起止减速，消除匀速机械感
    - 完成反馈：单次扫描结束时区域边框高亮闪烁一次（与截图动作联动）
    - 速度自适应：大区域自动提高每帧移动量，视觉速度均匀
    """

    # 光带分层：(颜色, 高度px)，中心近白两侧渐深，总高 25px；颜色来自答题卡标记色
    _BAND = _scan_band_palette(MARKER_COLORS_HEX['card'])
    _BAND_H = sum(h for _, h in _BAND)
    _FRAME_COLOR = MARKER_COLORS_HEX['card']
    _FRAME_BORDER = 3

    def __init__(self, root):
        import tkinter as tk
        self._root = root
        self._band_wins = []  # [(Toplevel, height)]
        self._frame_wins = {}  # part -> Toplevel（边框闪烁用）
        self._job = None
        self._flash_job = None
        self._looping = False
        self._rect = (0, 0, 0, 0)  # (x, y, w, h) 供边框闪烁使用

        for color, height in self._BAND:
            win = tk.Toplevel(root)
            win.overrideredirect(True)
            win.attributes('-topmost', True)
            win.attributes('-toolwindow', True)
            win.configure(bg=color)
            win.withdraw()
            self._band_wins.append((win, height))

        for part in ('top', 'bottom', 'left', 'right'):
            win = tk.Toplevel(root)
            win.overrideredirect(True)
            win.attributes('-topmost', True)
            win.attributes('-toolwindow', True)
            win.configure(bg=self._FRAME_COLOR)
            win.withdraw()
            self._frame_wins[part] = win

    @staticmethod
    def _ease(ratio):
        """正弦缓动：0→1 先加速后减速。"""
        import math
        ratio = min(1.0, max(0.0, ratio))
        return 0.5 - 0.5 * math.cos(ratio * math.pi)

    def _adaptive_duration(self, h, duration_ms):
        """大区域自动提速（减少总时长），小区域略微放慢，视觉速度均匀。"""
        duration_ms = max(200, int(duration_ms))
        if h > 900:
            return int(duration_ms * 0.7)
        if h < 200:
            return int(duration_ms * 1.2)
        return duration_ms

    def _layout_band(self, x, y, w, line_y):
        """在 line_y 位置铺开渐变光带窗口。"""
        band_top = line_y
        for win, height in self._band_wins:
            win.geometry(f'{max(1, w)}x{height}+{x}+{band_top}')
            band_top += height

    def _show_band(self):
        for win, _ in self._band_wins:
            win.deiconify()
            win.lift()

    def _hide_band(self):
        for win, _ in self._band_wins:
            win.withdraw()

    def _show_frame(self):
        x, y, w, h = self._rect
        if w <= 0 or h <= 0:
            return
        b = self._FRAME_BORDER
        self._frame_wins['top'].geometry(f'{w}x{b}+{x}+{y}')
        self._frame_wins['bottom'].geometry(f'{w}x{b}+{x}+{y + h - b}')
        self._frame_wins['left'].geometry(f'{b}x{h}+{x}+{y}')
        self._frame_wins['right'].geometry(f'{b}x{h}+{x + w - b}+{y}')
        for win in self._frame_wins.values():
            win.deiconify()
            win.lift()

    def _hide_frame(self):
        for win in self._frame_wins.values():
            win.withdraw()

    def _flash_frame(self, times=2, interval_ms=70):
        """边框高亮闪烁 times 次（亮→灭→亮→灭），用于扫描完成的采集反馈。"""
        if self._flash_job:
            try:
                self._root.after_cancel(self._flash_job)
            except Exception:
                pass
            self._flash_job = None

        def blink(count):
            if count >= times * 2:
                self._hide_frame()
                self._flash_job = None
                return
            if count % 2 == 0:
                self._show_frame()
            else:
                self._hide_frame()
            self._flash_job = self._root.after(interval_ms, blink, count + 1)

        blink(0)

    def start(self, x, y, w, h, duration_ms=900):
        """单次扫描，扫完边框闪烁反馈后自动隐藏。"""
        self.hide()
        x, y, w, h = int(x), int(y), int(w), int(h)
        self._rect = (x, y, w, h)
        duration_ms = self._adaptive_duration(h, duration_ms)
        frames = max(20, duration_ms // 16)
        step = 0

        def draw():
            nonlocal step
            if step > frames:
                self._hide_band()
                self._flash_frame()
                return
            ratio = self._ease(step / frames)
            line_y = y + int(max(0, h - self._BAND_H) * ratio)
            self._layout_band(x, y, w, line_y)
            self._show_band()
            step += 1
            self._job = self._root.after(max(1, duration_ms // frames), draw)

        draw()

    def start_loop(self, x, y, w, h, duration_ms=800):
        """循环扫描，直到调用 hide() 才停止。"""
        self.hide()
        x, y, w, h = int(x), int(y), int(w), int(h)
        self._rect = (x, y, w, h)
        duration_ms = self._adaptive_duration(h, duration_ms)
        frames = max(20, duration_ms // 16)
        self._looping = True
        step = 0

        def draw():
            nonlocal step
            if not self._looping:
                return
            if step > frames:
                step = 0  # 回到顶部继续循环
            ratio = self._ease(step / frames)
            line_y = y + int(max(0, h - self._BAND_H) * ratio)
            self._layout_band(x, y, w, line_y)
            self._show_band()
            step += 1
            self._job = self._root.after(max(1, duration_ms // frames), draw)

        draw()

    def hide(self):
        if self._job:
            try:
                self._root.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        if self._flash_job:
            try:
                self._root.after_cancel(self._flash_job)
            except Exception:
                pass
            self._flash_job = None
        self._looping = False
        self._hide_band()
        self._hide_frame()

    def destroy(self):
        self.hide()
        for win, _ in self._band_wins:
            try:
                win.destroy()
            except Exception:
                pass
        for win in self._frame_wins.values():
            try:
                win.destroy()
            except Exception:
                pass
        self._band_wins.clear()
        self._frame_wins.clear()

    def _destroy(self):
        self.destroy()

def _tk_marker_main(markers_out, ready_event):
    """在独立线程中：创建 tk root → 创建标记窗口 → 进入 mainloop"""
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()

    for mt in ('card', 'score', 'submit'):
        markers_out[mt] = TkMarker(root, mt)
    markers_out['_scan_line'] = TkScanLine(root)

    # 记住上次的标记框位置与大小，但启动时默认隐藏（不自动弹出干扰用户）；
    # 点“添加标记”时 WindowApi.show_marker 会读取这里的存档，按上次位置显示。
    saved_rects = _load_marker_state()
    for mt in MARKER_ORDER:
        rect = saved_rects.get(mt)
        if isinstance(rect, dict):
            log.info('已记住标记框 %s 位置（启动默认隐藏）: x=%s y=%s w=%s h=%s',
                     mt, rect.get('x'), rect.get('y'), rect.get('w'), rect.get('h'))

    ready_event.set()

    def poll_queue():
        try:
            while True:
                cmd = _marker_queue.get_nowait()
                action = cmd[0]
                try:
                    if action == 'show':
                        _, mtype, x, y, w, h = cmd[:6]
                        m = markers_out.get(mtype)
                        if m:
                            m._show(x, y, w, h)
                    elif action == 'hide':
                        m = markers_out.get(cmd[1])
                        if m:
                            m._hide()
                    elif action == 'scan_card':
                        _, x, y, w, h, duration_ms = cmd
                        scan_line = markers_out.get('_scan_line')
                        if scan_line:
                            scan_line.start(x, y, w, h, duration_ms)
                    elif action == 'scan_card_loop':
                        _, x, y, w, h, duration_ms = cmd
                        scan_line = markers_out.get('_scan_line')
                        if scan_line:
                            scan_line.start_loop(x, y, w, h, duration_ms)
                    elif action == 'scan_flash':
                        _, times = cmd
                        scan_line = markers_out.get('_scan_line')
                        if scan_line:
                            scan_line._flash_frame(times)
                    elif action == 'hide_scan':
                        scan_line = markers_out.get('_scan_line')
                        if scan_line:
                            scan_line.hide()
                    elif action == 'destroy':
                        for m in list(markers_out.values()):
                            m._destroy()
                        markers_out.clear()
                    elif action == 'quit':
                        for m in list(markers_out.values()):
                            m._destroy()
                        markers_out.clear()
                        root.quit()
                        return
                except Exception:
                    # 单条命令异常不能拖垮整个标记线程（否则标记会永久失去响应）
                    log.exception('标记线程处理命令异常: action=%s cmd=%s', action, cmd[:2])
                finally:
                    # 同步命令（show/hide）携带 threading.Event，执行完必须唤醒调用方，
                    # 保证 JS 侧在标记真正显示/隐藏完成前不会继续截图或读取坐标
                    if len(cmd) >= 2 and isinstance(cmd[-1], threading.Event):
                        cmd[-1].set()
        except queue.Empty:
            pass
        root.after(50, poll_queue)

    root.after(100, poll_queue)
    root.mainloop()


# ---------- 单实例控制 ----------

def set_window_topmost(hwnd):
    try:
        HWND_TOPMOST = -1
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        ctypes.windll.user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
    except Exception:
        pass


def ensure_single_instance():
    mutex_name = "Local\\AI_Grader_9a3f2d71-e184-4e6e-bc28-8c5a1f6e9d4b"
    ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    if ctypes.windll.kernel32.GetLastError() == 183:
        hwnd = ctypes.windll.user32.FindWindowW(None, "好帮手AI阅卷 1.0.0")
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)
            set_window_topmost(hwnd)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        sys.exit(0)


def hide_from_taskbar(hwnd):
    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x80
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)
    ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004 | 0x0010)


# ---------- 基础工具 ----------

def find_free_port(start=5000):
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) != 0:
                return port
    raise RuntimeError("无法找到可用端口")


def check_activated():
    from license import is_activated
    return is_activated()


def get_screen_size():
    try:
        import pyautogui
        w, h = pyautogui.size()
        return w, h
    except Exception:
        return 1920, 1080


def get_work_area_dip():
    """工作区（去掉任务栏），换算成 DIP/逻辑像素，与 pywebview 使用的单位一致。

    pyautogui.size() 返回的是物理像素，而 pywebview 的 width/height/x/y 按 DIP 处理；
    在 125%/150%/200% 缩放下直接用物理像素会把窗口算得比屏幕还高，导致只露出半截。
    返回 (left, top, width, height)，取不到时返回 None。
    """
    user32 = ctypes.windll.user32
    try:
        work = wintypes.RECT()
        if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0):  # SPI_GETWORKAREA
            return None
        scale = 1.0
        try:
            gdi32 = ctypes.windll.gdi32
            dc = user32.GetDC(0)
            try:
                dpi_x = gdi32.GetDeviceCaps(dc, 88)  # LOGPIXELSX
                if dpi_x:
                    scale = dpi_x / 96.0
            finally:
                user32.ReleaseDC(0, dc)
        except Exception:
            pass
        width = (work.right - work.left) / scale
        height = (work.bottom - work.top) / scale
        if width <= 0 or height <= 0:
            return None
        return (work.left / scale, work.top / scale, width, height)
    except Exception:
        log.warning('读取工作区失败，改用 pyautogui 屏幕尺寸', exc_info=True)
        return None


def calc_window_size():
    """按真实工作区（DIP）计算窗口尺寸：小屏/高缩放机器也不会超出屏幕。"""
    area = get_work_area_dip()
    if area:
        avail_w, avail_h = area[2], area[3]
    else:
        avail_w, avail_h = get_screen_size()
    w = min(500, max(360, int(avail_w * 0.9)))
    # 占工作区 94% 高，上限 945；不再设 809 的硬下限（那正是小屏显示不全的原因）
    h = min(945, max(480, int(avail_h * 0.94)))
    h = min(h, int(avail_h))
    return w, h


def fit_window_into_work_area(hwnd, top_margin_ratio=0.02):
    """把窗口收进真实工作区并上移，解决高 DPI 缩放下的“窗口超出屏幕、只露出 60%”问题。

    calc_window_size() 用的是 pyautogui 的物理像素，而 pywebview 按 DIP 定位窗口；
    125%/150% 缩放下两者不一致，窗口会比屏幕还高。这里统一用 Win32 实测坐标纠正：
    GetWindowRect 与 SPI_GETWORKAREA 处于同一坐标系，因此不受缩放比例影响。
    """
    user32 = ctypes.windll.user32
    try:
        work = wintypes.RECT()
        if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0):  # SPI_GETWORKAREA
            return
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return
        win_w = rect.right - rect.left
        win_h = rect.bottom - rect.top
        avail_w = work.right - work.left
        avail_h = work.bottom - work.top
        if win_w <= 0 or win_h <= 0 or avail_w <= 0 or avail_h <= 0:
            return

        new_w = min(win_w, avail_w)
        new_h = min(win_h, avail_h)
        x = work.left + max(0, (avail_w - new_w) // 2)
        y = work.top + max(0, int(avail_h * top_margin_ratio))   # 贴顶留 2% 边距，整体抬高
        y = max(work.top, min(y, work.bottom - new_h))           # 保证底部不被任务栏切掉
        # SWP_NOZORDER(0x4) 保留置顶状态，SWP_NOACTIVATE(0x10) 不抢焦点
        user32.SetWindowPos(hwnd, 0, x, y, new_w, new_h, 0x0004 | 0x0010)
        log.info('窗口校正: %dx%d -> %dx%d @(%d,%d) 工作区=%dx%d',
                 win_w, win_h, new_w, new_h, x, y, avail_w, avail_h)
    except Exception:
        log.warning('窗口位置校正失败', exc_info=True)


# ---------- WindowApi（暴露给 JS） ----------

class WindowApi:

    def __init__(self, window, markers):
        self._window = window
        self._markers = markers  # type -> TkMarker

    def minimize(self):
        self._window.minimize()

    def move(self, dx, dy):
        try:
            mhwnd = int(self._window.native.Handle.ToInt64())
            r = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(mhwnd, ctypes.byref(r))
            ctypes.windll.user32.SetWindowPos(
                mhwnd, 0,
                r.left + dx, r.top + dy,
                0, 0,
                0x0004 | 0x0001,
            )
        except Exception:
            pass

    def close(self):
        try:
            self._window.hide()
        except Exception:
            pass
        os._exit(0)

    # ---- 标记控制 ----

    @staticmethod
    def _queue_sync(cmd, timeout=2.0):
        """把命令投递给 tkinter 线程，并等待它真正执行完成。

        原来 show/hide 只是把命令丢进队列就返回，JS 侧紧接着读取标记坐标时
        tkinter 线程往往还没把窗口显示出来（轮询间隔 50ms），导致连续自动批改
        第二份时把“尚未恢复显示”误判为“标记丢失”而停止。这里通过 Event 等待
        tkinter 线程执行完毕，保证调用返回时标记窗口状态已生效。
        """
        done = threading.Event()
        _marker_queue.put(tuple(cmd) + (done,))
        if not done.wait(timeout):
            log.warning('标记线程命令执行超时: %s', cmd[:2])

    def show_marker(self, mtype):
        """通过队列通知 tkinter 线程显示标记（等待真正显示完成）。位置计算在主线程完成。"""
        m = self._markers.get(mtype)
        if not m:
            return

        # 已经显示过（含启动时复用的上次位置）就不再挪动，避免用户重新点按钮时标记跳走
        if m.is_visible():
            return

        saved = _load_marker_state().get(mtype)
        if isinstance(saved, dict):
            try:
                self._queue_sync(('show', mtype, int(saved['x']), int(saved['y']),
                                  int(saved['w']), int(saved['h'])))
                return
            except Exception:
                log.warning('应用上次标记位置失败，改用默认位置: %s', mtype, exc_info=True)

        try:
            mhwnd = int(self._window.native.Handle.ToInt64())
            r = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(mhwnd, ctypes.byref(r))
            main_x, main_y, main_w, main_h = r.left, r.top, r.right - r.left, r.bottom - r.top
        except Exception:
            main_x, main_y, main_w, main_h = 0, 0, 500, 800

        try:
            import pyautogui
            screen_w, screen_h = pyautogui.size()
        except Exception:
            screen_w, screen_h = 1920, 1080

        sw, sh = MARKER_SIZES[mtype]
        gap = 20
        max_w = max(MARKER_SIZES[mt][0] for mt in MARKER_ORDER)
        stack_h = sum(MARKER_SIZES[mt][1] for mt in MARKER_ORDER) + gap * (len(MARKER_ORDER) - 1)

        if main_x + main_w + gap + max_w <= screen_w:
            x = main_x + main_w + gap
        elif main_x - gap - max_w >= 0:
            x = main_x - gap - max_w
        else:
            x = screen_w - max_w - gap

        base_y = main_y
        if base_y + stack_h > screen_h:
            base_y = screen_h - stack_h - gap
        base_y = max(0, base_y)

        y = base_y
        for mt in MARKER_ORDER:
            if mt == mtype:
                break
            y += MARKER_SIZES[mt][1] + gap

        self._queue_sync(('show', mtype, x, y, sw, sh))

    def hide_marker(self, mtype):
        self._queue_sync(('hide', mtype))

    def hide_all_markers(self):
        for mt in MARKER_ORDER:
            self._queue_sync(('hide', mt))

    def show_marker_at(self, mtype, x, y, w, h):
        self._queue_sync(('show', mtype, int(x), int(y), int(w), int(h)))

    def scan_card_area(self, x, y, w, h, duration_ms=900):
        _marker_queue.put(('scan_card', int(x), int(y), int(w), int(h), int(duration_ms)))

    def scan_card_area_loop(self, x, y, w, h, duration_ms=800):
        """开始循环扫描答题卡区域，直到调用 hide_scan_line() 停止。"""
        _marker_queue.put(('scan_card_loop', int(x), int(y), int(w), int(h), int(duration_ms)))

    def hide_scan_line(self):
        _marker_queue.put(('hide_scan',))

    def scan_flash(self, times=2):
        """截图完成后触发边框高亮闪烁，作为"采集完成"反馈。"""
        _marker_queue.put(('scan_flash', max(1, int(times))))

    def get_marker_rect(self, mtype):
        m = self._markers.get(mtype)
        if m and m.is_visible():
            return m.get_rect()
        return None

    def get_all_marker_rects(self):
        result = {}
        for mt in ('card', 'score', 'submit'):
            r = self.get_marker_rect(mt)
            if r:
                result[mt] = r
        return result

    def is_marker_active(self, mtype):
        m = self._markers.get(mtype)
        return bool(m and m.is_visible())

    def get_all_active_markers(self):
        return [mt for mt in ('card', 'score', 'submit') if self.is_marker_active(mt)]


# ---------- 主入口 ----------

def main():
    ensure_single_instance()

    # 1. 启动 Flask
    port = find_free_port()
    os.environ['FLASK_PORT'] = str(port)
    os.environ['FLASK_DEBUG'] = '0'
    from app import app

    def run_flask():
        app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False, threaded=True)

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # 2. 检查激活状态
    activated = check_activated()
    url = f'http://127.0.0.1:{port}/' if activated else f'http://127.0.0.1:{port}/activate'

    # 3. 等待 Flask 就绪
    for _ in range(20):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.1)
            if s.connect_ex(('127.0.0.1', port)) == 0:
                s.close()
                break
            s.close()
        except Exception:
            pass
        time.sleep(0.1)

    win_w, win_h = calc_window_size()

    # 4. 启动 tkinter 标记线程（独立 mainloop）
    markers = {}
    marker_ready = threading.Event()

    marker_th = threading.Thread(
        target=_tk_marker_main,
        args=(markers, marker_ready),
        daemon=True,
    )
    marker_th.start()
    marker_ready.wait()

    # 5. 创建 pywebview 窗口
    api = WindowApi(None, markers)

    window = webview.create_window(
        title='好帮手AI阅卷 1.0.0',
        url=url,
        width=win_w,
        height=win_h,
        min_size=(500, 650),
        resizable=True,
        frameless=True,
        easy_drag=False,
        on_top=True,
        js_api=api,
    )

    api._window = window

    # UI 渲染之后再后台加载 OCR 模型：不与窗口创建 / WebView2 初始化抢 CPU 和磁盘
    def _warmup_ocr_after_ui(*args):
        if not activated:
            return  # 停在激活页，没必要加载模型
        try:
            from local_ocr import warmup_async
            warmup_async(delay=0.8)   # 让首屏先绘制完成再开始读模型
        except Exception:
            log.warning('安排本地 OCR 预热失败', exc_info=True)

    try:
        window.events.loaded += _warmup_ocr_after_ui
    except Exception:
        log.warning('window.events.loaded 不可用，改用定时预热', exc_info=True)
        threading.Timer(3.0, _warmup_ocr_after_ui).start()

    def remove_taskbar_icon():
        for _ in range(10):
            try:
                hwnd = int(window.native.Handle.ToInt64())
                if hwnd:
                    hide_from_taskbar(hwnd)
                    set_window_topmost(hwnd)
                    fit_window_into_work_area(hwnd)
                    break
            except Exception:
                pass
            time.sleep(0.05)
        # WebView2 首帧后尺寸才最终确定，再校正一次，避免仍按初始尺寸超出屏幕
        try:
            time.sleep(0.8)
            fit_window_into_work_area(int(window.native.Handle.ToInt64()))
        except Exception:
            pass

    threading.Thread(target=remove_taskbar_icon, daemon=True).start()

    # 6. 进入 webview 消息循环（阻塞直到窗口关闭）
    webview.start(gui='edgechromium', debug=False)

    # 7. 窗口关闭 → 停止标记线程 → 退出
    _marker_queue.put(('quit',))
    marker_th.join(timeout=2)
    os._exit(0)


if __name__ == '__main__':
    main()
