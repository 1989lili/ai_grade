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

MARKER_TRANSPARENT_COLOR = '#010203'

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
    """由四条独立细窗口组成的空心虚线标记框。框内没有窗口区域，不遮挡内容。"""

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
            line_id = canvas.create_line(0, 0, 1, 1, fill=self._color, width=3, dash=(10, 6))
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

    def _layout(self):
        x, y, w, h = self._rect['x'], self._rect['y'], self._rect['w'], self._rect['h']
        b = self._BORDER

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
        for win in self._wins.values():
            win.deiconify()
            win.lift()
        self._visible = True

    def _hide(self):
        for win in self._wins.values():
            win.withdraw()
        self._visible = False

    def _destroy(self):
        for win in list(self._wins.values()):
            win.destroy()
        self._wins.clear()
        self._canvases.clear()
        self._line_ids.clear()

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
