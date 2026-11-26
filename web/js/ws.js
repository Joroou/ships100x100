// WebSocket-клиент: автопереподключение и хранение ключа сессии (чтобы вернуться в партию после обрыва/F5).
const KEY = 'seabattle_session';

export class WSClient {
  constructor() {
    this.handlers = {};
    this.ws = null;
    this.retry = 0;
    this.connected = false;
  }

  on(type, fn) { (this.handlers[type] ||= []).push(fn); }
  emit(type, data) { (this.handlers[type] || []).forEach(fn => fn(data)); }

  getSession() { try { return JSON.parse(sessionStorage.getItem(KEY)); } catch { return null; } }
  saveSession(code, token) { try { sessionStorage.setItem(KEY, JSON.stringify({ code, token })); } catch { /* ignore */ } }
  clearSession() { try { sessionStorage.removeItem(KEY); } catch { /* ignore */ } }

  connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws = ws;
    ws.onopen = () => {
      this.connected = true;
      this.retry = 0;
      const s = this.getSession();
      if (s) this.send({ type: 'reconnect', code: s.code, token: s.token }); // вернуться в партию
      this.emit('_status', true);
    };
    ws.onmessage = ev => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      this.emit(msg.type, msg);
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.connected = false;
      this.emit('_status', false);
      const delay = Math.min(5000, 500 * 2 ** this.retry++);
      setTimeout(() => this.connect(), delay);
    };
    ws.onerror = () => ws.close();
  }

  send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj));
      return true;
    }
    return false;
  }
}
