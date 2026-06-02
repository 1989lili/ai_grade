ACTIVATION_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>好帮手AI阅卷 - 激活</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Microsoft YaHei', sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    height: 100vh; overflow: hidden;
    display: flex; flex-direction: column;
}
/* 可拖拽标题栏 */
.header {
    background: #e8f4f8; height: 52px; display: flex;
    justify-content: space-between; align-items: center;
    padding: 0 24px; flex-shrink: 0;
    -webkit-app-region: drag;
}
.header .title {
    font-size: 16px; font-weight: bold; color: #333;
    display: flex; align-items: center; gap: 8px;
}
.header .logo-sm {
    width: 28px; height: 28px; border-radius: 6px;
    background: linear-gradient(135deg, #4CAF50, #45a049);
    color: white; font-size: 14px; font-weight: bold;
    display: flex; align-items: center; justify-content: center;
}
.win-btns { display: flex; gap: 6px; }
.win-btn {
    width: 30px; height: 30px; border: none; border-radius: 4px;
    cursor: pointer; font-size: 14px; font-weight: bold;
    display: flex; align-items: center; justify-content: center;
    -webkit-app-region: no-drag;
}
.win-min { background: #ffc107; color: #333; }
.win-close { background: #dc3545; color: white; }
/* 主体内容 */
.body-wrap {
    flex: 1; display: flex; justify-content: center; align-items: center;
    -webkit-app-region: no-drag;
}
.card {
    background: white; border-radius: 16px; padding: 40px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.3);
    width: 100%; max-width: 460px;
}
h1 { text-align: center; color: #333; margin-bottom: 24px; font-size: 22px; }
.logo {
    width: 64px; height: 64px; margin: 0 auto 16px;
    background: linear-gradient(135deg, #4CAF50, #45a049);
    border-radius: 16px; display: flex; align-items: center; justify-content: center;
    color: white; font-size: 32px; font-weight: bold;
}
.section { margin-bottom: 20px; }
.label { font-size: 14px; color: #666; margin-bottom: 6px; font-weight: bold; }
.hwid-box {
    background: #f5f5f5; border: 1px solid #e0e0e0;
    border-radius: 8px; padding: 12px; font-size: 13px;
    word-break: break-all; color: #333; user-select: all;
    font-family: monospace;
}
.btn {
    width: 100%; padding: 12px; border: none; border-radius: 8px;
    font-size: 16px; font-weight: bold; cursor: pointer; transition: all 0.3s;
}
.btn-copy { background: #2196f3; color: white; margin-top: 8px; }
.btn-copy:hover { background: #1976d2; }
.btn-activate { background: #4CAF50; color: white; margin-top: 16px; }
.btn-activate:hover { background: #388E3C; }
.btn-activate:disabled { background: #ccc; cursor: not-allowed; }
input[type="text"] {
    width: 100%; padding: 12px; border: 2px solid #e0e0e0;
    border-radius: 8px; font-size: 14px; transition: border 0.3s;
}
input[type="text"]:focus { border-color: #2196f3; outline: none; }
.msg { margin-top: 12px; padding: 10px; border-radius: 6px; font-size: 14px; display: none; }
.msg.success { background: #e8f5e9; color: #2e7d32; display: block; }
.msg.error { background: #ffebee; color: #c62828; display: block; }
.note { margin-top: 16px; font-size: 12px; color: #999; text-align: center; }
</style>
</head>
<body>
<div class="header">
    <div class="title">
        <div class="logo-sm">好</div>
        <span>好帮手AI阅卷</span>
    </div>
    <div class="win-btns">
        <button class="win-btn win-min" id="btn-min">−</button>
        <button class="win-btn win-close" id="btn-close">×</button>
    </div>
</div>
<div class="body-wrap">
<div class="card">
    <div class="logo">好</div>
    <h1>好帮手AI阅卷 - 软件激活</h1>
    <div class="section">
        <div class="label">本机机器码</div>
        <div class="hwid-box" id="hwid">加载中...</div>
        <button class="btn btn-copy" onclick="copyHWID()">复制机器码</button>
    </div>
    <div class="section">
        <div class="label">激活码</div>
        <input type="text" id="licenseKey" placeholder="请输入激活码">
    </div>
    <button class="btn btn-activate" id="activateBtn" onclick="activate()">激活软件</button>
    <div class="msg" id="msg"></div>
    <div class="note">请将机器码发送给软件提供商以获取激活码</div>
</div>
</div>
<script>
function bindWindowControls() {
    function bind(api) {
        document.getElementById('btn-min').onclick = function () { api.minimize(); };
        document.getElementById('btn-close').onclick = function () { api.close(); };
    }
    window.addEventListener('pywebviewready', function () {
        if (window.pywebview && window.pywebview.api) bind(window.pywebview.api);
    });
    var n = 0;
    var t = setInterval(function () {
        if (window.pywebview && window.pywebview.api) { bind(window.pywebview.api); clearInterval(t); }
        if (++n > 30) clearInterval(t);
    }, 200);
}
bindWindowControls();

async function init() {
    try {
        const resp = await fetch('/api/hwid');
        const data = await resp.json();
        document.getElementById('hwid').textContent = data.hwid;
    } catch (e) {
        document.getElementById('hwid').textContent = '获取失败: ' + e.message;
    }
}
function copyHWID() {
    const hwid = document.getElementById('hwid').textContent;
    navigator.clipboard.writeText(hwid).then(function() {
        showMsg('机器码已复制到剪贴板', 'success');
    }).catch(function() {
        const input = document.createElement('textarea');
        input.value = hwid; document.body.appendChild(input);
        input.select(); document.execCommand('copy');
        document.body.removeChild(input);
        showMsg('机器码已复制到剪贴板', 'success');
    });
}
async function activate() {
    const licenseKey = document.getElementById('licenseKey').value.trim();
    if (!licenseKey) { showMsg('请输入激活码', 'error'); return; }
    const btn = document.getElementById('activateBtn');
    btn.disabled = true; btn.textContent = '激活中...';
    try {
        const resp = await fetch('/api/activate', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({licenseKey})
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showMsg('激活成功！正在跳转...', 'success');
            setTimeout(function() { window.location.href = '/'; }, 1500);
        } else {
            showMsg(data.message || '激活失败', 'error');
        }
    } catch (e) {
        showMsg('激活请求失败: ' + e.message, 'error');
    }
    btn.disabled = false; btn.textContent = '激活软件';
}
function showMsg(text, type) {
    const msg = document.getElementById('msg');
    msg.textContent = text; msg.className = 'msg ' + type;
}
init();
</script>
</body>
</html>
"""
