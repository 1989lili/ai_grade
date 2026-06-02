"""管理后台 - 许可证生成与设备管理。通过 /admin42 访问。"""

import functools
import datetime
from flask import Blueprint, request, jsonify, session, redirect

try:
    from .db import init_db, add_activation, get_activations, get_stats
    from .db import revoke_activation, verify_admin, get_activation_by_hwid
    from .license_gen import generate_license as sign_license
    from .hwid import generate_hwid
except ImportError:
    from db import init_db, add_activation, get_activations, get_stats  # type: ignore
    from db import revoke_activation, verify_admin, get_activation_by_hwid  # type: ignore
    from license_gen import generate_license as sign_license  # type: ignore
    from hwid import generate_hwid  # type: ignore

admin_bp = Blueprint('admin', __name__, url_prefix='/admin42')

SECRET_KEY = 'ai_grade_admin_secret_2026'
init_db()


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            if request.is_json:
                return jsonify({'status': 'error', 'message': '未登录'}), 401
            return redirect('/admin42/login')
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/login')
def login_page():
    if session.get('admin_logged_in'):
        return redirect('/admin42/')
    return ADMIN_LOGIN_HTML


@admin_bp.route('/')
@login_required
def dashboard():
    return ADMIN_PANEL_HTML


# ---------- API ----------

@admin_bp.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        return jsonify({'status': 'error', 'message': '请输入用户名和密码'})
    admin = verify_admin(username, password)
    if admin:
        session['admin_logged_in'] = True
        session['admin_username'] = username
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error', 'message': '用户名或密码错误'})


@admin_bp.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'status': 'success'})


@admin_bp.route('/api/check')
def api_check():
    return jsonify({'logged_in': session.get('admin_logged_in', False)})


@admin_bp.route('/api/stats')
@login_required
def api_stats():
    return jsonify(get_stats())


@admin_bp.route('/api/generate', methods=['POST'])
@login_required
def api_generate():
    data = request.json
    hwid = data.get('hwid', '').strip()
    expiry_days = data.get('expiryDays') or None
    device_label = data.get('deviceLabel', '').strip()
    note = data.get('note', '').strip()

    if not hwid:
        return jsonify({'status': 'error', 'message': '请输入机器码'})

    expiry = None
    if expiry_days:
        expiry = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=int(expiry_days))).isoformat()

    license_key = sign_license(hwid, int(expiry_days) if expiry_days else None)
    add_activation(hwid, license_key, expiry, device_label, note)

    return jsonify({
        'status': 'success',
        'licenseKey': license_key,
        'hwid': hwid,
        'expiry': expiry
    })


@admin_bp.route('/api/activations')
@login_required
def api_activations():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '').strip()
    rows, total = get_activations(page=page, search=search, status=status)
    per_page = 20
    return jsonify({
        'activations': rows,
        'total': total,
        'pages': max(1, (total + per_page - 1) // per_page),
        'page': page
    })


@admin_bp.route('/api/revoke', methods=['POST'])
@login_required
def api_revoke():
    data = request.json
    activation_id = data.get('id')
    if not activation_id:
        return jsonify({'status': 'error', 'message': '缺少ID'})
    revoke_activation(activation_id)
    return jsonify({'status': 'success'})


# ---------- 页面 HTML ----------

ADMIN_LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>管理后台 - 好帮手AI阅卷</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Microsoft YaHei',sans-serif;background:linear-gradient(135deg,#1a1a2e,#16213e);display:flex;justify-content:center;align-items:center;min-height:100vh}
.login-box{background:#fff;border-radius:16px;padding:48px 40px;box-shadow:0 20px 60px rgba(0,0,0,.4);width:400px}
h1{text-align:center;color:#1a1a2e;margin-bottom:8px;font-size:24px}
.sub{text-align:center;color:#999;margin-bottom:32px;font-size:13px}
.form-group{margin-bottom:20px}
.form-group label{display:block;font-size:14px;color:#666;margin-bottom:6px;font-weight:bold}
.form-group input{width:100%;padding:12px 16px;border:2px solid #e0e0e0;border-radius:8px;font-size:15px;transition:border .3s}
.form-group input:focus{border-color:#4facfe;outline:none}
.btn{width:100%;padding:14px;border:none;border-radius:8px;font-size:16px;font-weight:bold;cursor:pointer;background:linear-gradient(135deg,#4facfe,#00f2fe);color:#fff;transition:opacity .3s}
.btn:hover{opacity:.9}
.msg{margin-top:12px;padding:10px;border-radius:6px;font-size:14px;text-align:center;display:none}
.msg.error{background:#ffebee;color:#c62828;display:block}
</style>
</head>
<body>
<div class="login-box">
<h1>好帮手AI阅卷</h1>
<div class="sub">管理后台</div>
<div class="form-group">
<label>用户名</label><input type="text" id="username" placeholder="请输入用户名" autofocus>
</div>
<div class="form-group">
<label>密码</label><input type="password" id="password" placeholder="请输入密码" onkeydown="if(event.key==='Enter')login()">
</div>
<button class="btn" onclick="login()">登 录</button>
<div class="msg" id="msg"></div>
</div>
<script>
async function login(){
    const username=document.getElementById('username').value.trim()
    const password=document.getElementById('password').value.trim()
    if(!username||!password){showMsg('请输入用户名和密码','error');return}
    try{
        const r=await fetch('/admin42/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})})
        const d=await r.json()
        if(d.status==='success'){location.href='/admin42/'}else{showMsg(d.message,'error')}
    }catch(e){showMsg('登录失败: '+e.message,'error')}
}
function showMsg(t,c){const m=document.getElementById('msg');m.textContent=t;m.className='msg '+c}
</script>
</body>
</html>
"""

ADMIN_PANEL_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>管理后台 - 好帮手AI阅卷</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Microsoft YaHei',sans-serif;background:#f5f6fa;min-height:100vh}
.header{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:0 32px;display:flex;justify-content:space-between;align-items:center;height:64px}
.header h1{font-size:20px}
.header-right{display:flex;align-items:center;gap:16px}
.header-right span{font-size:14px;opacity:.8}
.logout-btn{background:#e74c3c;color:#fff;border:none;padding:8px 20px;border-radius:6px;cursor:pointer;font-size:13px}
.logout-btn:hover{background:#c0392b}
.tabs{display:flex;background:#fff;border-bottom:2px solid #e0e0e0;padding:0 32px}
.tab{padding:16px 28px;cursor:pointer;font-size:15px;color:#666;border-bottom:3px solid transparent;margin-bottom:-2px;transition:all .2s}
.tab:hover{color:#333}
.tab.active{color:#1a73e8;border-bottom-color:#1a73e8;font-weight:bold}
.main{padding:24px 32px;max-width:1400px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;margin-bottom:32px}
.card{background:#fff;border-radius:12px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.card .num{font-size:36px;font-weight:bold;margin-bottom:4px}
.card .label{font-size:14px;color:#999}
.card.total .num{color:#1a73e8}
.card.active .num{color:#27ae60}
.card.revoked .num{color:#e74c3c}
.card.today .num{color:#f39c12}
.section{background:#fff;border-radius:12px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,.06);margin-bottom:24px}
.section h2{font-size:18px;margin-bottom:20px;color:#333;padding-bottom:12px;border-bottom:2px solid #f0f0f0}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
.form-group label{display:block;font-size:13px;color:#666;margin-bottom:4px;font-weight:bold}
.form-group input,.form-group select{width:100%;padding:10px 14px;border:2px solid #e0e0e0;border-radius:8px;font-size:14px;transition:border .2s}
.form-group input:focus,.form-group select:focus{border-color:#4facfe;outline:none}
.form-group.full{grid-column:1/-1}
.btn-primary{background:linear-gradient(135deg,#4facfe,#00f2fe);color:#fff;border:none;padding:12px 32px;border-radius:8px;font-size:15px;font-weight:bold;cursor:pointer}
.btn-primary:hover{opacity:.9}
.btn-danger{background:#e74c3c;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px}
.btn-danger:hover{background:#c0392b}
.result-box{background:#f0fff4;border:2px solid #27ae60;border-radius:8px;padding:16px;margin-top:12px;display:none}
.result-box.show{display:block}
.result-box .license-key{font-family:monospace;font-size:12px;word-break:break-all;background:#fff;padding:10px;border-radius:6px;margin-top:8px;border:1px solid #e0e0e0;user-select:all}
.copy-btn{background:#27ae60;color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:12px;margin-top:8px}
.toolbar{display:flex;gap:12px;margin-bottom:16px;align-items:center}
.search-input{flex:1;padding:10px 14px;border:2px solid #e0e0e0;border-radius:8px;font-size:14px}
.status-select{padding:10px 14px;border:2px solid #e0e0e0;border-radius:8px;font-size:14px}
.table-wrapper{overflow-x:auto}
table{width:100%;border-collapse:collapse}
th{text-align:left;padding:12px 8px;font-size:13px;color:#999;border-bottom:2px solid #e0e0e0;white-space:nowrap}
td{padding:10px 8px;font-size:13px;border-bottom:1px solid #f0f0f0}
tr:hover td{background:#f8f9ff}
.badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:bold}
.badge.active{background:#e8f5e9;color:#27ae60}
.badge.revoked{background:#ffebee;color:#e74c3c}
.pagination{display:flex;gap:8px;justify-content:center;margin-top:16px}
.pagination button{padding:8px 14px;border:1px solid #e0e0e0;border-radius:6px;background:#fff;cursor:pointer;font-size:13px}
.pagination button.active{background:#1a73e8;color:#fff;border-color:#1a73e8}
.pagination button:disabled{opacity:.5;cursor:not-allowed}
.msg{position:fixed;top:20px;right:20px;padding:12px 24px;border-radius:8px;font-size:14px;font-weight:bold;z-index:999;animation:slideIn .3s}
.msg.success{background:#e8f5e9;color:#27ae60}
.msg.error{background:#ffebee;color:#e74c3c}
@keyframes slideIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
.mt-12{margin-top:12px}
.text-muted{color:#999;font-size:12px}
</style>
</head>
<body>
<div class="header">
<h1>好帮手AI阅卷 - 管理后台</h1>
<div class="header-right">
<span id="username"></span>
<button class="logout-btn" onclick="logout()">退出登录</button>
</div>
</div>
<div class="tabs">
<div class="tab active" data-tab="generate">生成激活码</div>
<div class="tab" data-tab="list">激活记录</div>
</div>
<div class="main">
<div class="cards">
<div class="card total"><div class="num" id="stat-total">-</div><div class="label">总激活数</div></div>
<div class="card active"><div class="num" id="stat-active">-</div><div class="label">有效激活</div></div>
<div class="card revoked"><div class="num" id="stat-revoked">-</div><div class="label">已撤销</div></div>
<div class="card today"><div class="num" id="stat-today">-</div><div class="label">今日新增</div></div>
</div>

<div id="tab-generate" class="section">
<h2>生成激活码</h2>
<div class="form-row">
<div class="form-group full">
<label>机器码 (HWID)</label>
<input type="text" id="gen-hwid" placeholder="粘贴用户提供的机器码">
<div class="text-muted mt-12" style="margin-top:4px">用户启动软件后在激活页面可以看到机器码</div>
</div>
</div>
<div class="form-row">
<div class="form-group">
<label>有效期</label>
<select id="gen-expiry">
<option value="">永久有效</option>
<option value="30">30天</option>
<option value="90">90天</option>
<option value="180">180天</option>
<option value="365">1年</option>
<option value="custom">自定义天数</option>
</select>
</div>
<div class="form-group" id="custom-days-group" style="display:none">
<label>自定义天数</label>
<input type="number" id="gen-custom-days" placeholder="输入天数" min="1">
</div>
</div>
<div class="form-row">
<div class="form-group">
<label>设备备注 (可选)</label>
<input type="text" id="gen-label" placeholder="例如：张三的电脑">
</div>
<div class="form-group">
<label>内部备注 (可选)</label>
<input type="text" id="gen-note" placeholder="例如：VIP客户">
</div>
</div>
<button class="btn-primary" onclick="generateLicense()">生成激活码</button>
<div class="result-box" id="result">
<div style="font-weight:bold;color:#27ae60">激活码已生成</div>
<div style="margin-top:8px;font-size:13px;color:#666">机器码: <strong id="result-hwid"></strong></div>
<div style="font-size:13px;color:#666">有效期: <strong id="result-expiry"></strong></div>
<div class="license-key" id="result-key"></div>
<button class="copy-btn" onclick="copyLicense()">复制激活码</button>
<button class="copy-btn" onclick="copyAll()" style="margin-left:8px;background:#1a73e8">复制激活信息</button>
</div>
</div>

<div id="tab-list" class="section" style="display:none">
<h2>激活记录</h2>
<div class="toolbar">
<input type="text" class="search-input" id="search" placeholder="搜索机器码 / 设备备注..." onkeyup="debounceSearch()">
<select class="status-select" id="status-filter" onchange="loadActivations()">
<option value="">全部状态</option>
<option value="active">有效</option>
<option value="revoked">已撤销</option>
</select>
</div>
<div class="table-wrapper">
<table>
<thead>
<tr><th>ID</th><th>机器码</th><th>设备备注</th><th>内部备注</th><th>激活时间</th><th>到期时间</th><th>状态</th><th>操作</th></tr>
</thead>
<tbody id="activation-tbody"></tbody>
</table>
</div>
<div class="pagination" id="pagination"></div>
</div>
</div>
<div class="msg" id="toast" style="display:none"></div>

<script>
let currentTab='generate'
let searchTimer=null

document.querySelectorAll('.tab').forEach(t=>{
t.addEventListener('click',function(){
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'))
    this.classList.add('active')
    currentTab=this.dataset.tab
    document.getElementById('tab-generate').style.display=currentTab==='generate'?'':'none'
    document.getElementById('tab-list').style.display=currentTab==='list'?'':'none'
    if(currentTab==='list') loadActivations()
})})

document.getElementById('gen-expiry').addEventListener('change',function(){
    document.getElementById('custom-days-group').style.display=this.value==='custom'?'':'none'
})

document.getElementById('username').textContent='admin'

async function checkAuth(){
    try{const r=await fetch('/admin42/api/check');const d=await r.json();if(!d.logged_in){location.href='/admin42/login'}}catch(e){}
}
async function loadStats(){
    try{const r=await fetch('/admin42/api/stats');const d=await r.json();
    document.getElementById('stat-total').textContent=d.total
    document.getElementById('stat-active').textContent=d.active
    document.getElementById('stat-revoked').textContent=d.revoked
    document.getElementById('stat-today').textContent=d.today
    }catch(e){}
}

async function generateLicense(){
    const hwid=document.getElementById('gen-hwid').value.trim()
    if(!hwid){toast('请输入机器码','error');return}
    let expiryDays=null
    const sel=document.getElementById('gen-expiry').value
    if(sel==='custom'){expiryDays=parseInt(document.getElementById('gen-custom-days').value)||null}
    else if(sel){expiryDays=parseInt(sel)}
    const deviceLabel=document.getElementById('gen-label').value.trim()
    const note=document.getElementById('gen-note').value.trim()
    try{
        const r=await fetch('/admin42/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hwid,expiryDays,deviceLabel,note})})
        const d=await r.json()
        if(d.status==='success'){
            document.getElementById('result').classList.add('show')
            document.getElementById('result-key').textContent=d.licenseKey
            document.getElementById('result-hwid').textContent=d.hwid
            document.getElementById('result-expiry').textContent=d.expiry||'永久有效'
            toast('激活码生成成功','success')
            loadStats()
        }else{toast(d.message,'error')}
    }catch(e){toast('生成失败: '+e.message,'error')}
}

function copyLicense(){
    const key=document.getElementById('result-key').textContent
    navigator.clipboard.writeText(key).then(()=>toast('已复制到剪贴板','success'))
}
function copyAll(){
    const hwid=document.getElementById('result-hwid').textContent
    const key=document.getElementById('result-key').textContent
    const expiry=document.getElementById('result-expiry').textContent
    const text='机器码: '+hwid+'\n激活码: '+key+'\n有效期: '+expiry
    navigator.clipboard.writeText(text).then(()=>toast('激活信息已复制','success'))
}

async function loadActivations(page=1){
    const search=document.getElementById('search').value.trim()
    const status=document.getElementById('status-filter').value
    try{
        const r=await fetch('/admin42/api/activations?page='+page+'&search='+encodeURIComponent(search)+'&status='+status)
        const d=await r.json()
        const tbody=document.getElementById('activation-tbody')
        tbody.innerHTML=d.activations.map(a=>'<tr>'+
            '<td>'+a.id+'</td>'+
            '<td style="font-family:monospace;font-size:11px" title="'+a.hwid+'">'+a.hwid.substring(0,16)+'...</td>'+
            '<td>'+escapeHtml(a.device_label||'-')+'</td>'+
            '<td>'+escapeHtml(a.note||'-')+'</td>'+
            '<td>'+formatDate(a.created_at)+'</td>'+
            '<td>'+formatDate(a.expiry)||'永久'+'</td>'+
            '<td><span class="badge '+a.status+'">'+(a.status==='active'?'有效':'已撤销')+'</span></td>'+
            '<td>'+(a.status==='active'?'<button class="btn-danger" onclick="revokeActivation('+a.id+')">撤销</button>':'')+'</td>'+
        '</tr>').join('')
        if(d.activations.length===0) tbody.innerHTML='<tr><td colspan="8" style="text-align:center;color:#999;padding:40px">暂无记录</td></tr>'
        renderPagination(d.page,d.pages)
    }catch(e){toast('加载失败: '+e.message,'error')}
}

function revokeActivation(id){
    if(!confirm('确定要撤销此激活吗？撤销后该设备将无法使用。')) return
    fetch('/admin42/api/revoke',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})})
    .then(r=>r.json()).then(d=>{
        if(d.status==='success'){toast('已撤销','success');loadActivations();loadStats()}
        else{toast(d.message,'error')}
    }).catch(e=>toast('操作失败','error'))
}

function renderPagination(page,totalPages){
    const el=document.getElementById('pagination')
    if(totalPages<=1){el.innerHTML='';return}
    let html='<button '+(page<=1?'disabled':'')+' onclick="loadActivations('+(page-1)+')">上一页</button>'
    for(let i=1;i<=totalPages;i++){
        html+='<button class="'+(i===page?'active':'')+'" onclick="loadActivations('+i+')">'+i+'</button>'
    }
    html+='<button '+(page>=totalPages?'disabled':'')+' onclick="loadActivations('+(page+1)+')">下一页</button>'
    el.innerHTML=html
}

function debounceSearch(){
    clearTimeout(searchTimer)
    searchTimer=setTimeout(()=>loadActivations(),300)
}

function formatDate(d){if(!d)return '永久';try{return new Date(d).toLocaleDateString('zh-CN')}catch(e){return d}}
function escapeHtml(s){if(!s)return '-';const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function toast(msg,type){
    const el=document.getElementById('toast')
    el.textContent=msg;el.className='msg '+type;el.style.display='block'
    setTimeout(()=>el.style.display='none',3000)
}
async function logout(){
    await fetch('/admin42/api/logout',{method:'POST'})
    location.href='/admin42/login'
}

checkAuth()
loadStats()
</script>
</body>
</html>
"""
