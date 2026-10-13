#!/usr/bin/env python3
"""Local Engineer Control Center prototype.

Local-first web UI for read-only session monitoring, direct Bonsai chat, and a
persistent instruction queue. Queue items are intentionally NOT executed yet.
Bind to loopback by default. API endpoints require a bearer token.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hmac
import json
import os
import pathlib
import secrets
import threading
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import live_server

HOME = pathlib.Path.home()
STATE = pathlib.Path(os.environ.get(
    "LOCAL_ENGINEER_STATE", str(HOME / ".local" / "state" / "local-engineer")
))
CONTROL_DIR = STATE / "control-center"
TASKS_PATH = CONTROL_DIR / "tasks.json"
TOKEN_PATH = CONTROL_DIR / "auth.token"
API_BASE = os.environ.get("BONSAI_API_BASE", "http://127.0.0.1:8080/v1")
MAX_BODY = 16_000
MAX_TASKS = 1000
TASK_LOCK = threading.Lock()
AUTH_TOKEN = ""


HTML = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>Local Engineer Control Center</title>
<style>
:root{color-scheme:dark;--bg:#101512;--panel:#19211d;--line:#303c35;--text:#e8eee9;--muted:#9eada3;--green:#8bd2a7;--accent:#245b43;--red:#ffaaa2}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px system-ui,-apple-system,sans-serif}
main{max-width:1040px;margin:auto;padding:16px}.head{display:flex;gap:12px;align-items:center;margin-bottom:18px}
.logo{display:grid;place-items:center;width:44px;height:44px;background:var(--accent);border-radius:12px;font-weight:800;font-size:18px}
h1{font-size:20px;margin:0}.sub,.muted{color:var(--muted);font-size:12px}.sub{margin-top:3px}
.badge{margin-left:auto;border:1px solid var(--line);border-radius:99px;padding:6px 10px;font-size:11px;color:var(--green)}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin-bottom:13px}
.stat,.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px;min-width:0}
.stat label{display:block;color:var(--muted);font-size:12px}.stat strong{display:block;font-size:15px;margin-top:5px;overflow-wrap:anywhere}
.tabs{display:flex;gap:7px;margin:14px 0}.tabs button{flex:1}
button,input,textarea,select{font:inherit}button{cursor:pointer;background:#202b24;color:var(--text);border:1px solid #405046;border-radius:9px;padding:9px 12px}
button.primary{background:var(--accent);border-color:#4a8a68}button:disabled{opacity:.5;cursor:default}
input,textarea,select{width:100%;background:#111a14;color:var(--text);border:1px solid #405046;border-radius:9px;padding:11px;min-width:0}
textarea{resize:vertical;min-height:85px}.row{display:flex;gap:8px;align-items:center}.row>*{min-width:0}
.section-title{font-weight:700;margin-bottom:11px;display:flex;justify-content:space-between;align-items:center;gap:8px}
.hidden{display:none!important}.feed{display:flex;flex-direction:column;gap:10px;max-height:48vh;overflow:auto;margin:10px 0}
.msg{border:1px solid var(--line);border-radius:11px;padding:11px;line-height:1.55;white-space:pre-wrap;overflow-wrap:anywhere}
.msg.user{align-self:flex-end;background:#202c24;max-width:94%}.msg.ai{align-self:flex-start;max-width:100%}
.who{font-size:11px;color:var(--muted);margin-bottom:5px}.task{padding:12px 0;border-top:1px solid var(--line)}
.task:first-child{border-top:0}.task-name{font-weight:650;overflow-wrap:anywhere}.task-meta{color:var(--muted);font-size:11px;margin-top:5px}
.tag{font-size:10px;border:1px solid var(--line);padding:4px 7px;border-radius:7px;white-space:nowrap}
.log{border-top:1px solid var(--line);padding:9px 0;font-size:12px;overflow-wrap:anywhere}.log:first-of-type{border-top:0}
.foot{font-size:11px;color:var(--muted);line-height:1.6;margin-top:12px}
#authbox{margin-bottom:13px}#notice{font-size:12px;color:var(--green);margin-top:8px;white-space:pre-wrap}
@media(min-width:700px){.grid{grid-template-columns:repeat(4,minmax(0,1fr))}main{padding:24px}.two{display:grid;grid-template-columns:1.2fr .8fr;gap:13px;align-items:start}}
</style>
</head>
<body><main>
<header class="head"><div class="logo">LE</div><div><h1>Local Engineer Control Center</h1><div class="sub">ローカル優先 · Bonsai · タスクキュー</div></div><span class="badge">プロトタイプ</span></header>
<section class="panel" id="authbox"><div class="section-title">ローカル接続トークン</div><div class="row"><input id="token" type="password" autocomplete="current-password" placeholder="ターミナルに表示されたトークン"><button id="connect" class="primary">接続</button></div><div class="foot">このトークンはAPI操作の認証に使います。共有端末では保存しないでください。</div><div id="notice"></div></section>
<section class="grid">
<div class="stat"><label>AIエンジン</label><strong>Bonsai 27B</strong><div class="sub" id="bonsai">接続確認前</div></div>
<div class="stat"><label>Local Engineer</label><strong id="session">未取得</strong><div class="sub" id="phase">状態未取得</div></div>
<div class="stat"><label>ビルド</label><strong id="build">未確認</strong><div class="sub">実際の記録値</div></div>
<div class="stat"><label>指示キュー</label><strong id="count">未取得</strong><div class="sub">永続保存</div></div>
</section>
<nav class="tabs"><button class="primary" data-tab="chat">AIチャット</button><button data-tab="queue">指示キュー</button><button data-tab="activity">イベント</button></nav>
<div class="two">
<section class="panel" id="tab-chat"><div class="section-title">Bonsaiに相談 <span class="tag">ローカルAPI</span></div>
<div class="feed" id="feed"><div class="msg ai"><div class="who">Local Engineer</div>接続後、Bonsaiに技術相談できます。このチャットは相談用で、コード編集やビルドを直接実行しません。</div></div>
<textarea id="chat-input" placeholder="例：STM32F411でWS2812をPWM＋DMA駆動する際の確認事項を整理して"></textarea>
<div class="row" style="margin-top:8px"><button id="send" class="primary">Bonsaiへ送信</button><span class="muted">相談のみ・編集は行いません</span></div>
</section>
<section class="panel" id="tab-queue"><div class="section-title">指示キュー <span class="tag">実行待ち</span></div>
<textarea id="task-input" placeholder="実行したい作業を具体的に記入"></textarea>
<div class="row" style="margin-top:8px"><select id="priority" aria-label="優先度"><option value="normal">通常</option><option value="high">高</option><option value="low">低</option></select><button id="add-task" class="primary">キューに追加</button></div>
<div class="foot">現在はキューへの永続登録までです。自動実行ランナーは未接続なので、追加してもファイル変更やビルドは開始されません。</div>
<div id="tasks" style="margin-top:12px"></div>
</section>
</div>
<section class="panel hidden" id="tab-activity" style="margin-top:13px"><div class="section-title">セッションイベント</div><div id="events"><div class="muted">接続すると取得します。</div></div></section>
<div class="foot">セキュリティ：APIはBearerトークン必須。標準では127.0.0.1だけにバインドします。LAN/Tailscale公開時も無認証公開しないでください。</div>
</main>
<script>
(function(){
const $=id=>document.getElementById(id);let token=sessionStorage.getItem('le-token')||'';let lastSeq=0;let connected=false;
$('token').value=token;
function api(path,opts={}){opts.headers=Object.assign({'Authorization':'Bearer '+token},opts.headers||{});return fetch(path,opts).then(async r=>{const d=await r.json().catch(()=>({error:'invalid response'}));if(!r.ok)throw new Error(d.error||('HTTP '+r.status));return d})}
function note(s){$('notice').textContent=s}
function addMsg(role,text){const el=document.createElement('div');el.className='msg '+role;const who=document.createElement('div');who.className='who';who.textContent=role==='user'?'あなた':'Bonsai 27B';const body=document.createElement('div');body.textContent=text;el.append(who,body);$('feed').append(el);$('feed').scrollTop=$('feed').scrollHeight}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
async function refresh(){
 if(!connected)return;
 try{
  const s=await api('/api/status');$('session').textContent=s.session||'セッションなし';$('phase').textContent=(s.status||'不明')+' · '+(s.phase||'');$('build').textContent=s.build_status||'未記録';$('bonsai').textContent=s.bonsai?'API接続OK':'API未確認';
  const q=await api('/api/tasks');$('count').textContent=q.tasks.length+'件';renderTasks(q.tasks);
  const ev=await api('/api/events?since='+lastSeq);if(ev.events.length){lastSeq=Math.max(lastSeq,...ev.events.map(e=>e._seq||0));const box=$('events');if(lastSeq===Math.max(...ev.events.map(e=>e._seq||0))&&box.querySelector('.muted'))box.replaceChildren();for(const e of ev.events){const d=document.createElement('div');d.className='log';d.textContent=[e._seq,e.tool||e.type||'event',e.result||e.message||''].filter(Boolean).join(' · ').slice(0,1000);box.append(d)}}
 }catch(e){note('接続エラー: '+e.message)}
}
function renderTasks(tasks){const box=$('tasks');box.replaceChildren();if(!tasks.length){const p=document.createElement('div');p.className='muted';p.textContent='キューは空です。';box.append(p);return}
 tasks.slice().reverse().forEach(t=>{const el=document.createElement('div');el.className='task';const row=document.createElement('div');row.className='row';const name=document.createElement('div');name.className='task-name';name.style.flex='1';name.textContent=t.title;const tag=document.createElement('span');tag.className='tag';tag.textContent=t.status;row.append(name,tag);const meta=document.createElement('div');meta.className='task-meta';meta.textContent='優先度: '+t.priority+' · '+t.created_at+' · '+t.id.slice(0,8);const del=document.createElement('button');del.textContent='削除';del.style.marginTop='8px';del.addEventListener('click',async()=>{try{await api('/api/tasks/'+encodeURIComponent(t.id),{method:'DELETE'});note('タスクを削除しました');refresh()}catch(e){note(e.message)}});el.append(row,meta,del);box.append(el)})
}
$('connect').addEventListener('click',async()=>{token=$('token').value.trim();if(!token){note('トークンを入力してください');return}sessionStorage.setItem('le-token',token);connected=true;try{const s=await api('/api/status');note('接続しました');$('bonsai').textContent=s.bonsai?'API接続OK':'API未確認';await refresh()}catch(e){connected=false;note('接続できません: '+e.message)}});
$('send').addEventListener('click',async()=>{const text=$('chat-input').value.trim();if(!text)return;if(!connected){note('先に接続してください');return}addMsg('user',text);$('chat-input').value='';$('send').disabled=true;try{const d=await api('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})});addMsg('ai',d.reply||'(応答なし)')}catch(e){addMsg('ai','エラー: '+e.message);note(e.message)}finally{$('send').disabled=false}});
$('chat-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey))$('send').click()});
$('add-task').addEventListener('click',async()=>{const title=$('task-input').value.trim();if(!title){$('task-input').focus();return}if(!connected){note('先に接続してください');return}try{await api('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,priority:$('priority').value})});$('task-input').value='';note('キューに保存しました（未実行）');await refresh()}catch(e){note(e.message)}});
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('primary',x===b));['chat','queue','activity'].forEach(t=>$('tab-'+t).classList.toggle('hidden',t!==b.dataset.tab))}));
if(token){connected=true;refresh()}setInterval(refresh,5000);
})();
</script></body></html>"""


def _ensure_control_dir() -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONTROL_DIR, 0o700)
    except OSError:
        pass


def load_tasks() -> list[dict]:
    try:
        data = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []


def save_tasks(tasks: list[dict]) -> None:
    _ensure_control_dir()
    temp = TASKS_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, TASKS_PATH)


def add_task(title: str, priority: str = "normal") -> dict:
    title = " ".join(str(title).split())
    if not title or len(title) > 1000:
        raise ValueError("title must contain 1-1000 characters")
    if priority not in ("low", "normal", "high"):
        raise ValueError("priority must be low, normal, or high")
    with TASK_LOCK:
        tasks = load_tasks()
        if len(tasks) >= MAX_TASKS:
            raise ValueError("task queue is full")
        task = {
            "id": uuid.uuid4().hex,
            "title": title,
            "priority": priority,
            "status": "queued",
            "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        tasks.append(task)
        save_tasks(tasks)
        return task


def delete_task(task_id: str) -> bool:
    with TASK_LOCK:
        tasks = load_tasks()
        remaining = [task for task in tasks if task.get("id") != task_id]
        if len(remaining) == len(tasks):
            return False
        save_tasks(remaining)
        return True


def ensure_token() -> str:
    _ensure_control_dir()
    if TOKEN_PATH.exists():
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass
    return token


def bonsai_chat(message: str) -> str:
    message = str(message).strip()
    if not message or len(message) > 4000:
        raise ValueError("message must contain 1-4000 characters")
    model = os.environ.get("BONSAI_MODEL", "").strip()
    if not model:
        models_request = urllib.request.Request(API_BASE.rstrip("/") + "/models", method="GET")
        try:
            with urllib.request.urlopen(models_request, timeout=5) as response:
                models_data = json.loads(response.read(500_000).decode("utf-8"))
            available = models_data.get("data", [])
            model = str(available[0].get("id", "")) if available else ""
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, AttributeError, TypeError):
            model = ""
    if not model:
        model = "bonsai"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are the planning-only chat assistant inside Local Engineer Control Center. "
                    "Answer in Japanese unless asked otherwise. Help reason about software/firmware tasks. "
                    "You have no tools and cannot inspect or edit files, run builds, or execute queued tasks. "
                    "Never claim you performed an action or verified hardware."
                ),
            },
            {"role": "user", "content": message},
        ],
        "temperature": 0.2,
        "max_tokens": 700,
        "stream": False,
    }
    request = urllib.request.Request(
        API_BASE.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read(2_000_000).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("Bonsai API unavailable or returned invalid data") from exc
    try:
        return str(data["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Bonsai API response did not contain a chat reply") from exc


def current_status() -> dict:
    session = live_server.latest_session()
    status = live_server.status_payload(session)
    status["bonsai"] = False
    request = urllib.request.Request(API_BASE.rstrip("/") + "/models", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            status["bonsai"] = response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        pass
    return status


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalEngineerControlCenter/0.1"

    def _send_json(self, data: dict | list, code: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        prefix = "Bearer "
        return supplied.startswith(prefix) and hmac.compare_digest(
            supplied[len(prefix):], AUTH_TOKEN
        )

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_BODY:
            raise ValueError("request body must be 1-16000 bytes")
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON object required")
        return data

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            raw = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, 401)
            return
        if path == "/api/status":
            self._send_json(current_status())
        elif path == "/api/tasks":
            with TASK_LOCK:
                self._send_json({"tasks": load_tasks()})
        elif path == "/api/events":
            from urllib.parse import parse_qs
            query = parse_qs(urlparse(self.path).query)
            try:
                since = max(0, int(query.get("since", ["0"])[0]))
            except ValueError:
                since = 0
            session = live_server.latest_session()
            self._send_json({"events": live_server.load_events(session, since=since, limit=100)})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, 401)
            return
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/tasks":
                task = add_task(body.get("title", ""), body.get("priority", "normal"))
                self._send_json({"task": task}, 201)
            elif path == "/api/chat":
                reply = bonsai_chat(body.get("message", ""))
                self._send_json({"reply": reply})
            else:
                self._send_json({"error": "not found"}, 404)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
        except RuntimeError as exc:
            self._send_json({"error": str(exc)}, 503)

    def do_DELETE(self) -> None:
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, 401)
            return
        path = urlparse(self.path).path
        prefix = "/api/tasks/"
        if path.startswith(prefix):
            task_id = path[len(prefix):]
            if not task_id or "/" in task_id or not delete_task(task_id):
                self._send_json({"error": "task not found"}, 404)
            else:
                self._send_json({"ok": True})
            return
        self._send_json({"error": "not found"}, 404)

    def log_message(self, fmt: str, *args) -> None:
        print("[control-center] " + fmt % args, flush=True)


def main() -> None:
    global AUTH_TOKEN
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    AUTH_TOKEN = ensure_token()
    print(f"Local Engineer Control Center: http://127.0.0.1:{args.port}", flush=True)
    print("API bearer token (enter in the page; stored with mode 0600):", flush=True)
    print(AUTH_TOKEN, flush=True)
    if args.host not in ("127.0.0.1", "::1", "localhost") and not AUTH_TOKEN:
        raise SystemExit("refusing non-loopback bind without authentication")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
