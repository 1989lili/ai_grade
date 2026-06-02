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

MARKER_COLORS_HEX = {
    'card':   '#e91e63',
    'score':  '#2196f3',
    'submit': '#9c27b0',
}

MARKER_LABELS = {
    'card':   '答题卡区域',
    'score':  '打分框位置',
    'submit': '提交按钮位置',
}

MARKER_SIZES = {
    'card':   (400, 300),
    'score':  (300, 175),
    'submit': (300, 175),
}

# ---------- 标记线程通信 ----------

_marker_queue = queue.Queue()  # 主线程 → tkinter 线程


class TkMarker:
    """tkinter Toplevel 标记窗口。支持拖拽移动 + 边缘拖拽缩放。"""

    _RESIZE_MARGIN = 8
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
    }

    def __init__(self, root, mtype):
        import tkinter as tk
        self._mtype = mtype
        self._color = MARKER_COLORS_HEX[mtype]
        self._win = tk.Toplevel(root)
        self._win.overrideredirect(True)
        self._win.attributes('-alpha', 0.12)
        self._win.attributes('-topmost', True)
        self._win.attributes('-toolwindow', True)
        self._win.configure(bg=self._color)
        self._win.withdraw()

        # 交互状态
        self._drag_offset_x = 0
        self._drag_offset_y = 0
        self._resize_dir = None  # 非 None 表示正在缩放
        self._resize_start = None  # (root_x, root_y, win_x, win_y, w, h)

        # 绑定事件
        self._win.bind('<Button-1>', self._on_press)
        self._win.bind('<B1-Motion>', self._on_move)
        self._win.bind('<ButtonRelease-1>', self._on_release)

        self._win.bind('<Motion>', self._on_motion)
        self._win.bind('<Leave>', self._on_leave)

        self._visible = False
        self._rect = {'x': 0, 'y': 0, 'w': MARKER_SIZES[mtype][0], 'h': MARKER_SIZES[mtype][1]}

    # ---- 边缘检测 ----

    def _get_resize_dir(self, event):
        """根据鼠标在窗口内的位置返回缩放方向，不在边缘则返回 None。"""
        x, y = event.x, event.y
        w = self._win.winfo_width()
        h = self._win.winfo_height()
        m = self._RESIZE_MARGIN

        left = x < m
        right = x > w - m
        top = y < m
        bottom = y > h - m

        if top and left:     return 'nw'
        if top and right:    return 'ne'
        if bottom and left:  return 'sw'
        if bottom and right: return 'se'
        if left:             return 'w'
        if right:            return 'e'
        if top:              return 'n'
        if bottom:           return 's'
        return None

    # ---- 事件处理 ----

    def _on_motion(self, event):
        d = self._get_resize_dir(event)
        cursor = self._RESIZE_CURSORS.get(d, 'arrow')
        self._win.configure(cursor=cursor)

    def _on_leave(self, event):
        self._win.configure(cursor='arrow')

    def _on_press(self, event):
        d = self._get_resize_dir(event)
        if d:
            self._resize_dir = d
            self._resize_start = (
                event.x_root, event.y_root,
                self._win.winfo_x(), self._win.winfo_y(),
                self._win.winfo_width(), self._win.winfo_height(),
            )
        else:
            self._resize_dir = None
            self._drag_offset_x = event.x_root - self._win.winfo_x()
            self._drag_offset_y = event.y_root - self._win.winfo_y()

    def _on_move(self, event):
        if self._resize_dir:
            self._do_resize(event)
        else:
            x = event.x_root - self._drag_offset_x
            y = event.y_root - self._drag_offset_y
            self._win.geometry(f'+{x}+{y}')

    def _on_release(self, event):
        self._resize_dir = None
        self._resize_start = None
        self._update_rect()

    def _do_resize(self, event):
        sx, sy, wx, wy, sw, sh = self._resize_start
        dx = event.x_root - sx
        dy = event.y_root - sy
        d = self._resize_dir

        new_x, new_y = wx, wy
        new_w, new_h = sw, sh

        if 'e' in d:
            new_w = max(self._MIN_W, sw + dx)
        if 'w' in d:
            new_w = max(self._MIN_W, sw - dx)
            new_x = wx + sw - new_w
        if 's' in d:
            new_h = max(self._MIN_H, sh + dy)
        if 'n' in d:
            new_h = max(self._MIN_H, sh - dy)
            new_y = wy + sh - new_h

        self._win.geometry(f'{new_w}x{new_h}+{new_x}+{new_y}')

    def _update_rect(self):
        self._rect = {
            'x': self._win.winfo_x(),
            'y': self._win.winfo_y(),
            'w': self._win.winfo_width(),
            'h': self._win.winfo_height(),
        }

    # ---- 公共接口（通过 queue 在 tkinter 线程中调用） ----

    def get_rect(self):
        return dict(self._rect)

    def is_visible(self):
        return self._visible

    def _show(self, x, y, w, h):
        self._win.geometry(f'{w}x{h}+{x}+{y}')
        self._win.deiconify()
        self._win.lift()
        self._visible = True
        self._rect = {'x': x, 'y': y, 'w': w, 'h': h}

    def _hide(self):
        self._win.withdraw()
        self._visible = False

    def _destroy(self):
        self._win.destroy()


def _tk_marker_main(markers_out, ready_event):
    """在独立线程中：创建 tk root → 创建标记窗口 → 进入 mainloop"""
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()

    for mt in ('card', 'score', 'submit'):
        markers_out[mt] = TkMarker(root, mt)

    ready_event.set()

    def poll_queue():
        try:
            while True:
                cmd = _marker_queue.get_nowait()
                action = cmd[0]
                if action == 'show':
                    _, mtype, x, y, w, h = cmd
                    m = markers_out.get(mtype)
                    if m:
                        m._show(x, y, w, h)
                elif action == 'hide':
                    m = markers_out.get(cmd[1])
                    if m:
                        m._hide()
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
        except queue.Empty:
            pass
        root.after(50, poll_queue)

    root.after(100, poll_queue)
    root.mainloop()


# ---------- 单实例控制 ----------

def ensure_single_instance():
    mutex_name = "Local\\AI_Grader_9a3f2d71-e184-4e6e-bc28-8c5a1f6e9d4b"
    ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    if ctypes.windll.kernel32.GetLastError() == 183:
        hwnd = ctypes.windll.user32.FindWindowW(None, "好帮手AI阅卷 1.0.0")
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)
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


def calc_window_size():
    sw, sh = get_screen_size()
    w = 500
    h = max(809, min(945, int(sh * 0.9009)))
    return w, h


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

    def show_marker(self, mtype):
        """通过队列通知 tkinter 线程显示标记。位置计算在主线程完成。"""
        m = self._markers.get(mtype)
        if not m:
            return

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

        if main_x + main_w + gap + sw <= screen_w:
            x = main_x + main_w + gap
        elif main_x - gap - sw >= 0:
            x = main_x - gap - sw
        else:
            x = screen_w - sw - gap

        y = main_y
        if y + sh > screen_h:
            y = screen_h - sh - gap
        y = max(0, y)

        _marker_queue.put(('show', mtype, x, y, sw, sh))

    def hide_marker(self, mtype):
        _marker_queue.put(('hide', mtype))

    def hide_all_markers(self):
        for mt in ('card', 'score', 'submit'):
            _marker_queue.put(('hide', mt))

    def show_marker_at(self, mtype, x, y, w, h):
        _marker_queue.put(('show', mtype, int(x), int(y), int(w), int(h)))

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
        app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)

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
        js_api=api,
    )

    api._window = window

    def remove_taskbar_icon():
        for _ in range(10):
            try:
                hwnd = int(window.native.Handle.ToInt64())
                if hwnd:
                    hide_from_taskbar(hwnd)
                    break
            except Exception:
                pass
            time.sleep(0.05)

    threading.Thread(target=remove_taskbar_icon, daemon=True).start()

    # 6. 进入 webview 消息循环（阻塞直到窗口关闭）
    webview.start(gui='edgechromium', debug=False)

    # 7. 窗口关闭 → 停止标记线程 → 退出
    _marker_queue.put(('quit',))
    marker_th.join(timeout=2)
    os._exit(0)


if __name__ == '__main__':
    main()
