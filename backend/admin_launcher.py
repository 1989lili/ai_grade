"""好帮手AI阅卷 - 管理端（仅管理员持有，绝不随用户版分发）。"""
import sys
import os
import socket
import threading
import time
import logging
import webview

if getattr(sys, 'frozen', False):
    sys.path.insert(0, sys._MEIPASS)
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.getLogger('werkzeug').setLevel(logging.WARNING)

os.environ['ADMIN_MODE'] = '1'


def find_free_port(start=5100):
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) != 0:
                return port
    raise RuntimeError("无法找到可用端口")


def main():
    from flask import Flask
    from flask_cors import CORS

    app = Flask(__name__)
    app.secret_key = 'ai_grade_admin_secret_2026'
    CORS(app)

    from admin import admin_bp
    app.register_blueprint(admin_bp)

    port = find_free_port()

    def run_flask():
        app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    time.sleep(1)

    url = f'http://127.0.0.1:{port}/admin42/'

    window = webview.create_window(
        title='好帮手AI阅卷 - 管理端',
        url=url,
        width=1200,
        height=800,
        min_size=(900, 600),
        resizable=True,
    )

    webview.start(gui='edgechromium', debug=False)
    os._exit(0)


if __name__ == '__main__':
    main()
