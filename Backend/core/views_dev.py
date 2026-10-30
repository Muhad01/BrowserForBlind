"""Developer WebSocket test interface (Milestone 4, Step 7).

Accessible only in DEBUG mode. Self-contained HTML with Web Speech synthesis and log viewer.
"""
from django.conf import settings
from django.http import Http404, HttpResponse


def ws_test_page(request):
    """Serve single-page developer test workbench for WebSocket testing."""
    if not settings.DEBUG:
        raise Http404("Developer tools are only available in DEBUG mode.")

    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CIGHT-BROWSER | WebSocket Test Bench</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }
    .container { max-width: 900px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }
    .card { background: #1e293b; border-radius: 8px; padding: 20px; border: 1px solid #334155; }
    h1 { font-size: 1.5rem; margin-top: 0; color: #38bdf8; }
    h2 { font-size: 1.1rem; margin-top: 0; color: #94a3b8; }
    .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    input[type="text"], input[type="password"] {
      background: #0f172a; border: 1px solid #475569; color: #f8fafc; padding: 10px 14px;
      border-radius: 6px; font-size: 14px; flex: 1; min-width: 180px;
    }
    button {
      background: #2563eb; color: #fff; border: none; padding: 10px 18px; border-radius: 6px;
      font-size: 14px; font-weight: 500; cursor: pointer; transition: background 0.2s;
    }
    button:hover { background: #1d4ed8; }
    button.danger { background: #dc2626; }
    button.danger:hover { background: #b91c1c; }
    .status { padding: 6px 12px; border-radius: 20px; font-size: 13px; font-weight: 600; display: inline-flex; align-items: center; gap: 6px; }
    .status.connected { background: #064e3b; color: #34d399; }
    .status.disconnected { background: #450a0a; color: #f87171; }
    #log {
      background: #020617; border: 1px solid #1e293b; border-radius: 6px; padding: 14px;
      height: 350px; overflow-y: auto; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 13px; display: flex; flex-direction: column; gap: 8px;
    }
    .log-entry { padding: 6px 10px; border-radius: 4px; border-left: 3px solid #38bdf8; background: #0b1329; }
    .log-entry.event-browser_action { border-left-color: #3b82f6; }
    .log-entry.event-task_started { border-left-color: #10b981; }
    .log-entry.event-task_completed { border-left-color: #22c55e; }
    .log-entry.event-task_failed { border-left-color: #ef4444; }
    .log-entry.event-agent_status { border-left-color: #eab308; }
    .time { color: #64748b; margin-right: 8px; }
    .event-badge { font-weight: 600; color: #38bdf8; margin-right: 8px; }
    .speak-text { color: #f1f5f9; font-weight: 500; }
  </style>
</head>
<body>
<div class="container">
  <div class="card">
    <h1>CIGHT-BROWSER WebSocket Workbench</h1>
    <div class="row">
      <span>Status:</span>
      <span id="statusIndicator" class="status disconnected">Disconnected</span>
      <span id="userIndicator" style="color: #94a3b8; font-size: 14px;"></span>
    </div>
  </div>

  <div class="card" id="authSection">
    <h2>1. Login</h2>
    <div class="row">
      <input type="text" id="usernameInput" placeholder="Username" value="demo">
      <input type="password" id="passwordInput" placeholder="Password" value="devpassword123">
      <button onclick="login()">Log In & Connect WS</button>
    </div>
  </div>

  <div class="card" id="commandSection">
    <h2>2. Command Input</h2>
    <div class="row">
      <input type="text" id="commandInput" placeholder="Enter simulated voice command (e.g. Search Wikipedia for artificial intelligence)" style="flex: 2;">
      <button onclick="sendCommand()">Send Command</button>
      <button class="danger" onclick="stopTask()">Stop</button>
    </div>
  </div>

  <div class="card">
    <div class="row" style="justify-content: space-between; margin-bottom: 10px;">
      <h2 style="margin: 0;">3. Live Event Stream</h2>
      <label style="font-size: 13px; color: #94a3b8;">
        <input type="checkbox" id="speechToggle" checked> Speech Synthesis Enabled
      </label>
    </div>
    <div id="log"></div>
  </div>
</div>

<script>
let ws = null;
let currentTicket = null;

function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

async function ensureCsrf() {
  await fetch('/api/csrf/', { credentials: 'same-origin' });
}

function appendLog(event, text, payload) {
  const log = document.getElementById('log');
  const entry = document.createElement('div');
  entry.className = 'log-entry event-' + event;
  const time = new Date().toLocaleTimeString();
  entry.innerHTML = `<span class="time">[${time}]</span><span class="event-badge">${event}</span><span class="speak-text">${text}</span>`;
  log.appendChild(entry);
  log.scrollTop = log.scrollHeight;
}

function speak(text) {
  if (!text || !document.getElementById('speechToggle').checked) return;
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.rate = 1.0;
    window.speechSynthesis.speak(utter);
  }
}

async function login() {
  await ensureCsrf();
  const username = document.getElementById('usernameInput').value;
  const password = document.getElementById('passwordInput').value;
  const csrftoken = getCookie('csrftoken');

  const res = await fetch('/api/auth/login/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrftoken || ''
    },
    credentials: 'same-origin',
    body: JSON.stringify({ username, password })
  });

  const data = await res.json();
  if (!res.ok) {
    alert('Login failed: ' + (data.message || data.error_code));
    return;
  }

  document.getElementById('userIndicator').innerText = `Logged in as: ${data.user.username}`;
  connectWebSocket();
}

async function connectWebSocket() {
  const csrftoken = getCookie('csrftoken');
  const ticketRes = await fetch('/api/ws-ticket/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrftoken || ''
    },
    credentials: 'same-origin'
  });

  if (!ticketRes.ok) {
    alert('Failed to obtain WebSocket ticket');
    return;
  }

  const { ticket } = await ticketRes.json();
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/browser/?ticket=${ticket}`;

  if (ws) {
    ws.close();
  }

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    const ind = document.getElementById('statusIndicator');
    ind.className = 'status connected';
    ind.innerText = 'Connected';
    appendLog('system', 'WebSocket connection established successfully.', {});
  };

  ws.onclose = (e) => {
    const ind = document.getElementById('statusIndicator');
    ind.className = 'status disconnected';
    ind.innerText = `Disconnected (code ${e.code})`;
    appendLog('system', `WebSocket closed with code ${e.code}`, {});
  };

  ws.onmessage = (event) => {
    const frame = JSON.parse(event.data);
    const speakText = frame.payload?.speak || frame.payload?.message || frame.payload?.result || '';
    appendLog(frame.event, speakText || JSON.stringify(frame.payload), frame.payload);
    if (frame.payload?.speak) {
      speak(frame.payload.speak);
    }
  };
}

function sendCommand() {
  const text = document.getElementById('commandInput').value.trim();
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) {
    alert('Enter a command and ensure WebSocket is connected.');
    return;
  }
  const msg = {
    type: 'voice_command',
    request_id: crypto.randomUUID(),
    payload: { text }
  };
  ws.send(JSON.stringify(msg));
  document.getElementById('commandInput').value = '';
}

function stopTask() {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    alert('WebSocket is not connected.');
    return;
  }
  const msg = {
    type: 'stop_task',
    request_id: crypto.randomUUID(),
    payload: { task_id: null }
  };
  ws.send(JSON.stringify(msg));
}
</script>
</body>
</html>"""
    return HttpResponse(html, content_type="text/html")
