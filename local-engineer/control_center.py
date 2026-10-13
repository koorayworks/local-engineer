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
STREAM_LOCK = threading.Lock()
ACTIVE_STREAMS: dict[str, dict] = {}
PLAN_LOCK = threading.Lock()
ACTIVE_PLANS: dict[str, dict] = {}


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
<div class="row" style="margin-top:8px"><button id="send" class="primary">Bonsaiへ送信</button><button id="cancel-chat" class="hidden">相談を中断</button><span class="muted">相談のみ・編集は行いません</span></div>
</section>
<section class="panel" id="tab-queue"><div class="section-title">指示キュー <span class="tag">実行待ち</span></div>
<div class="section-title" style="margin-top:4px">Bonsaiに作業計画を提案してもらう</div>
<textarea id="plan-goal" placeholder="例：RMK版PG1KBの現状を調べ、次に必要な作業を段階的に整理して"></textarea>
<div class="row" style="margin-top:8px"><button id="propose-plan" class="primary">計画を作成</button><button id="cancel-plan" class="hidden">計画生成を中断</button><span class="muted">提案だけでは実行されません</span></div>
<div id="plan-preview" style="margin:10px 0"></div>
<div class="section-title" style="margin-top:18px">手動でタスクを追加</div>
<textarea id="task-input" placeholder="キューに登録する作業を具体的に記入"></textarea>
<div class="row" style="margin-top:8px"><select id="priority" aria-label="優先度"><option value="normal">通常</option><option value="high">高</option><option value="low">低</option></select><button id="add-task" class="primary">キューに追加</button></div>
<div class="foot">Bonsaiの計画を確認してからキューに登録できます。キューは保存のみで、実行ランナーはまだ接続されていません。</div>
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
function addMsg(role,text){const el=document.createElement('div');el.className='msg '+role;const who=document.createElement('div');who.className='who';who.textContent=role==='user'?'あなた':'Bonsai 27B';const body=document.createElement('div');body.textContent=text;el.append(who,body);$('feed').append(el);$('feed').scrollTop=$('feed').scrollHeight;return body}
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
let activeChat=null;
$('send').addEventListener('click',async()=>{
 const text=$('chat-input').value.trim();if(!text)return;if(!connected){note('先に接続してください');return}
 addMsg('user',text);$('chat-input').value='';$('send').disabled=true;
 const cancel=$('cancel-chat');cancel.classList.remove('hidden');const answer=addMsg('ai','考えています…');
 const requestId=crypto.randomUUID();const controller=new AbortController();activeChat={requestId,controller};let received=false;
 try{
  const r=await fetch('/api/chat/stream',{method:'POST',headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({message:text,request_id:requestId}),signal:controller.signal});
  if(!r.ok){const d=await r.json().catch(()=>({error:'HTTP '+r.status}));throw new Error(d.error||('HTTP '+r.status))}
  if(!r.body)throw new Error('このブラウザはストリーミング表示に対応していません');
  const reader=r.body.getReader();const decoder=new TextDecoder();let pending='';
  while(true){const part=await reader.read();pending+=decoder.decode(part.value||new Uint8Array(),{stream:!part.done});const rows=pending.split('\n');pending=rows.pop()||'';for(const row of rows){if(!row.trim())continue;const item=JSON.parse(row);if(item.delta){if(!received){answer.textContent='';received=true}answer.textContent+=item.delta;$('feed').scrollTop=$('feed').scrollHeight}if(item.error)throw new Error(item.error)}if(part.done)break}
  if(pending.trim()){const item=JSON.parse(pending);if(item.delta){if(!received)answer.textContent='';received=true;answer.textContent+=item.delta}if(item.error)throw new Error(item.error)}
  if(!received)answer.textContent='回答を受信できませんでした（空の応答）';
 }catch(e){if(e.name==='AbortError')answer.textContent='相談を中断しました。';else{answer.textContent='エラー: '+e.message;note(e.message)}}finally{if(activeChat&&activeChat.requestId===requestId)activeChat=null;$('send').disabled=false;cancel.classList.add('hidden')}
});
$('cancel-chat').addEventListener('click',async()=>{
 if(!activeChat)return;const current=activeChat;$('cancel-chat').disabled=true;
 try{await api('/api/chat/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:current.requestId})})}catch(e){note('中断要求を送信しました。'+e.message)}
 current.controller.abort();$('cancel-chat').disabled=false;
});
$('chat-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey))$('send').click()});
let proposedPlan=null;let planRequest=null;
$('propose-plan').addEventListener('click',async()=>{
 const goal=$('plan-goal').value.trim();if(!goal){$('plan-goal').focus();return}
 if(!connected){note('先に接続してください');return}
 const btn=$('propose-plan');btn.disabled=true;btn.textContent='計画中…';$('plan-preview').replaceChildren();note('Bonsaiに計画を依頼しています…');
 const requestId=crypto.randomUUID();const controller=new AbortController();planRequest={requestId,controller};const cancel=$('cancel-plan');cancel.classList.remove('hidden');
 try{
  const data=await api('/api/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({goal,request_id:requestId}),signal:controller.signal});
  proposedPlan=data.plan;const box=$('plan-preview');const summary=document.createElement('div');summary.className='msg ai';summary.textContent=proposedPlan.summary;box.append(summary);
  const list=document.createElement('ol');for(const step of proposedPlan.steps){const li=document.createElement('li');li.style.margin='8px 0';li.textContent=step.title+'（'+step.priority+'）';list.append(li)}box.append(list);
  const approve=document.createElement('button');approve.className='primary';approve.textContent='この計画をキューに登録';approve.addEventListener('click',async()=>{
   approve.disabled=true;try{const saved=await api('/api/tasks/batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tasks:proposedPlan.steps})});note(saved.tasks.length+'件をキューに登録しました（未実行）');proposedPlan=null;box.replaceChildren();await refresh()}catch(e){note('登録できません: '+e.message);approve.disabled=false}
  });box.append(approve);note('計画案ができました。内容を確認してから登録してください。');
 }catch(e){if(e.name==='AbortError'){note('計画生成を中断しました');$('plan-preview').replaceChildren();proposedPlan=null}else{note('計画を作成できません: '+e.message)}}finally{if(planRequest&&planRequest.requestId===requestId)planRequest=null;btn.disabled=false;btn.textContent='計画を作成';cancel.classList.add('hidden')}
});
$('cancel-plan').addEventListener('click',async()=>{
 if(!planRequest)return;const current=planRequest;$('cancel-plan').disabled=true;
 try{await api('/api/plan/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:current.requestId})})}catch(e){note('計画の中断要求を送信しました。'+e.message)}
 current.controller.abort();$('cancel-plan').disabled=false;
});
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


def add_tasks(items: list[dict]) -> list[dict]:
    """Validate and persist a user-approved plan as queued tasks, atomically."""
    if not isinstance(items, list) or not 1 <= len(items) <= 8:
        raise ValueError("tasks must contain 1-8 items")
    prepared = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each task must be an object")
        title = " ".join(str(item.get("title", "")).split())
        priority = item.get("priority", "normal")
        if not title or len(title) > 1000:
            raise ValueError("title must contain 1-1000 characters")
        if priority not in ("low", "normal", "high"):
            priority = "normal"
        prepared.append((title, priority))
    with TASK_LOCK:
        tasks = load_tasks()
        if len(tasks) + len(prepared) > MAX_TASKS:
            raise ValueError("task queue is full")
        created = []
        for title, priority in prepared:
            created.append({
                "id": uuid.uuid4().hex,
                "title": title,
                "priority": priority,
                "status": "queued",
                "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            })
        tasks.extend(created)
        save_tasks(tasks)
        return created


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
    payload = {
        "model": _chat_model(),
        "messages": _chat_messages(message),
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


def bonsai_plan(goal: str, request_id: str | None = None) -> dict:
    """Ask Bonsai for a bounded JSON plan; planning never executes the tasks."""
    goal = str(goal).strip()
    if not goal or len(goal) > 2000:
        raise ValueError("goal must contain 1-2000 characters")
    system = (
        "You are the planning coordinator for Local Engineer. Answer in Japanese. "
        "Create a safe, practical sequence of at most 8 small tasks for the user's goal. "
        "Do not claim to have inspected files or performed work. Start with inspection, "
        "then hypothesis, implementation, tests, verification and diff review as appropriate. "
        "Do not propose commits, pushes, secret access, or destructive actions. "
        "Return ONLY a JSON object with this schema: "
        '{"summary":"short Japanese summary","steps":[{"title":"one actionable task","priority":"normal"}]}. '
        "Each step priority must be low, normal, or high. Include 1 to 8 steps."
    )
    payload = {
        "model": _chat_model(),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": goal}],
        "temperature": 0.2,
        "max_tokens": 1000,
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
            if request_id:
                with PLAN_LOCK:
                    state = ACTIVE_PLANS.get(request_id)
                    cancelled = state is None or state["cancelled"].is_set()
                    if state is not None:
                        state["response"] = response
                if cancelled:
                    response.close()
                    raise RuntimeError("plan generation cancelled")
            data = json.loads(response.read(2_000_000).decode("utf-8"))
        if request_id:
            with PLAN_LOCK:
                state = ACTIVE_PLANS.get(request_id)
                if state is None or state["cancelled"].is_set():
                    raise RuntimeError("plan generation cancelled")
        content = data["choices"][0]["message"]["content"]
    except RuntimeError:
        raise
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError, TypeError, OSError, ValueError) as exc:
        if request_id:
            with PLAN_LOCK:
                state = ACTIVE_PLANS.get(request_id)
                if state is not None and state["cancelled"].is_set():
                    raise RuntimeError("plan generation cancelled") from exc
        raise RuntimeError("Bonsai plan request failed or returned an invalid response") from exc
    if not isinstance(content, str):
        raise RuntimeError("Bonsai did not return a text plan")
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("Bonsai plan was not valid JSON; try a shorter goal")
    try:
        parsed = json.loads(content[start:end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("Bonsai plan was not valid JSON; try again") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("steps"), list):
        raise RuntimeError("Bonsai plan must contain a steps array")
    summary = " ".join(str(parsed.get("summary", "作業計画")).split())[:500]
    steps = []
    for item in parsed["steps"][:8]:
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("title", "")).split())
        if not title:
            continue
        steps.append({
            "title": title[:500],
            "priority": item.get("priority") if item.get("priority") in ("low", "normal", "high") else "normal",
        })
    if not steps:
        raise RuntimeError("Bonsai plan did not contain any usable steps")
    if request_id:
        with PLAN_LOCK:
            state = ACTIVE_PLANS.get(request_id)
            if state is None or state["cancelled"].is_set():
                raise RuntimeError("plan generation cancelled")
    return {"summary": summary or "作業計画", "steps": steps}


def _chat_model() -> str:
    model = os.environ.get("BONSAI_MODEL", "").strip()
    if model:
        return model
    models_request = urllib.request.Request(API_BASE.rstrip("/") + "/models", method="GET")
    try:
        with urllib.request.urlopen(models_request, timeout=5) as response:
            models_data = json.loads(response.read(500_000).decode("utf-8"))
        available = models_data.get("data", [])
        return str(available[0].get("id", "")) if available else "bonsai"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, AttributeError, TypeError):
        return "bonsai"


def _chat_messages(message: str) -> list[dict]:
    return [
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
    ]


def bonsai_stream(message: str, request_id: str | None = None):
    """Yield visible answer deltas; a cancel request closes the active upstream response."""
    message = str(message).strip()
    if not message or len(message) > 4000:
        raise ValueError("message must contain 1-4000 characters")
    payload = {
        "model": _chat_model(),
        "messages": _chat_messages(message),
        "temperature": 0.2,
        "max_tokens": 700,
        "stream": True,
    }
    request = urllib.request.Request(
        API_BASE.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    received = False
    finish_reason = None
    usage = None
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if request_id:
                with STREAM_LOCK:
                    state = ACTIVE_STREAMS.get(request_id)
                    cancelled = state is None or state["cancelled"].is_set()
                    if state is not None:
                        state["response"] = response
                if cancelled:
                    response.close()
                    yield {"cancelled": True}
                    return
            while True:
                if request_id:
                    with STREAM_LOCK:
                        state = ACTIVE_STREAMS.get(request_id)
                        cancelled = state is None or state["cancelled"].is_set()
                    if cancelled:
                        yield {"cancelled": True}
                        return
                raw_line = response.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                event_data = line[5:].strip()
                if event_data == "[DONE]":
                    break
                try:
                    event = json.loads(event_data)
                except json.JSONDecodeError:
                    continue
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                choices = event.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                if choice.get("finish_reason") is not None:
                    finish_reason = choice["finish_reason"]
                delta = (choice.get("delta") or {}).get("content")
                if isinstance(delta, str) and delta:
                    received = True
                    yield {"delta": delta}
        if not received:
            details = []
            if finish_reason is not None:
                details.append("finish_reason=" + str(finish_reason))
            if usage is not None:
                tokens = ", ".join(
                    key + "=" + str(usage[key])
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if key in usage
                )
                if tokens:
                    details.append("usage: " + tokens)
            suffix = "（" + "、".join(details) + "）" if details else ""
            yield {"error": "Bonsaiから表示可能な回答本文が返りませんでした" + suffix + "。reasoning_contentは表示していません。"}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
        cancelled = False
        if request_id:
            with STREAM_LOCK:
                state = ACTIVE_STREAMS.get(request_id)
                cancelled = state is not None and state["cancelled"].is_set()
        if cancelled:
            yield {"cancelled": True}
            return
        yield {"error": "Bonsai APIとの通信に失敗しました: " + str(exc)[:240]}


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
            elif path == "/api/plan":
                request_id = str(body.get("request_id", ""))
                if not request_id or len(request_id) > 100:
                    raise ValueError("request_id is required")
                with PLAN_LOCK:
                    if request_id in ACTIVE_PLANS:
                        raise ValueError("duplicate request_id")
                    ACTIVE_PLANS[request_id] = {"cancelled": threading.Event(), "response": None}
                try:
                    plan = bonsai_plan(body.get("goal", ""), request_id=request_id)
                    self._send_json({"plan": plan})
                finally:
                    with PLAN_LOCK:
                        ACTIVE_PLANS.pop(request_id, None)
            elif path == "/api/tasks/batch":
                created = add_tasks(body.get("tasks", []))
                self._send_json({"tasks": created}, 201)
            elif path == "/api/chat":
                reply = bonsai_chat(body.get("message", ""))
                self._send_json({"reply": reply})
            elif path == "/api/plan/cancel":
                request_id = str(body.get("request_id", ""))
                with PLAN_LOCK:
                    state = ACTIVE_PLANS.get(request_id)
                    if not request_id or state is None:
                        self._send_json({"ok": False, "error": "active plan generation not found"}, 404)
                        return
                    state["cancelled"].set()
                    upstream = state.get("response")
                    if upstream is not None:
                        try:
                            upstream.close()
                        except OSError:
                            pass
                self._send_json({"ok": True, "cancel_requested": True})
            elif path == "/api/chat/cancel":
                request_id = str(body.get("request_id", ""))
                with STREAM_LOCK:
                    state = ACTIVE_STREAMS.get(request_id)
                    if not request_id or state is None:
                        self._send_json({"ok": False, "error": "active consultation not found"}, 404)
                        return
                    state["cancelled"].set()
                    upstream = state.get("response")
                    if upstream is not None:
                        try:
                            upstream.close()
                        except OSError:
                            pass
                self._send_json({"ok": True, "cancel_requested": True})
            elif path == "/api/chat/stream":
                message = str(body.get("message", "")).strip()
                request_id = str(body.get("request_id", ""))
                if not message or len(message) > 4000:
                    raise ValueError("message must contain 1-4000 characters")
                if not request_id or len(request_id) > 100:
                    raise ValueError("request_id is required")
                with STREAM_LOCK:
                    if request_id in ACTIVE_STREAMS:
                        raise ValueError("duplicate request_id")
                    ACTIVE_STREAMS[request_id] = {"cancelled": threading.Event(), "response": None}
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-transform")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    for item in bonsai_stream(message, request_id=request_id):
                        if item.get("cancelled"):
                            break
                        self.wfile.write((json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8"))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    with STREAM_LOCK:
                        state = ACTIVE_STREAMS.get(request_id)
                        if state:
                            state["cancelled"].set()
                finally:
                    with STREAM_LOCK:
                        ACTIVE_STREAMS.pop(request_id, None)
                    self.close_connection = True
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
