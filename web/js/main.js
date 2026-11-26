// Точка входа фронта: связывает WebSocket, экраны, поле и панели.
// Клиент ничего не решает сам: он только показывает state от сервера и отправляет действия.
import { WSClient } from './ws.js';
import { Menu } from './menu.js';
import { BoardView, areaOrigin } from './board.js';
import { PlacementPanel } from './placement.js';
import { GadgetPanel } from './gadgets.js';

const $ = s => document.querySelector(s);
const ws = new WSClient();
let state = null;       // последнее полное состояние от сервера
let stateAt = 0;        // когда оно получено (для обратного отсчёта переподключения)
let orientation = 'h';  // 'h' — вправо, 'v' — вниз

function toast(text, kind = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`; el.textContent = text;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

function show(name) {
  for (const id of ['menu', 'lobby', 'game']) $('#screen-' + id).classList.toggle('hidden', id !== name);
}

// ---------- компоненты ----------
const board = new BoardView($('#board'), {
  onClick: onCellClick,
  onHover: c => { $('#coords').textContent = c ? `x: ${c.x + 1}, y: ${c.y + 1}` : ''; },
});
$('#z-in').onclick = () => board.zoomAt(1.3);
$('#z-out').onclick = () => board.zoomAt(1 / 1.3);
$('#z-fit').onclick = () => board.fit();

const menu = new Menu({
  onCreate: name => send({ type: 'create_lobby', name }),
  onJoin: (name, code) => send({ type: 'join_lobby', name, code }),
  onError: msg => toast(msg, 'error'),
});
const placement = new PlacementPanel($('#placement-panel'), {
  onReady: () => send({ type: 'ready' }), onRotate: toggleRotate, onChange: refreshTool,
});
const gadgets = new GadgetPanel($('#gadget-panel'), {
  onBuy: (kind, w, h) => send({ type: 'buy_gadget', kind, w, h }), onChange: refreshTool, onRotate: toggleRotate,
});

function send(obj) {
  if (!ws.send(obj)) toast('Нет соединения с сервером', 'error');
}

function toggleRotate() { orientation = orientation === 'h' ? 'v' : 'h'; render(); }
document.addEventListener('keydown', e => {
  if (e.code === 'KeyR' && !/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) toggleRotate();
});

// ---------- какой инструмент сейчас активен ----------
function currentTool() {
  if (!state) return null;
  if (state.phase === 'placement') return state.you.ready ? null : placement.getTool(orientation);
  if (state.phase === 'battle') return gadgets.getTool(orientation) || { kind: 'single', action: 'shoot' };
  return null;
}
function refreshTool() {
  board.setTool(currentTool());
  if (state && state.phase === 'placement') placement.render(state, orientation);
  if (state && state.phase === 'battle') gadgets.update();
}

function onCellClick(x, y) {
  const t = currentTool();
  if (!t) return;
  if (state.phase === 'battle' && state.turn !== 'you') return toast('Сейчас ход соперника', 'error');
  switch (t.action) {
    case 'place_ship': send({ type: 'place_ship', x, y, thick: t.t, length: t.l, orientation: t.orientation }); break;
    case 'shoot': send({ type: 'shoot', x, y }); break;
    case 'use_gadget': {
      const o = areaOrigin(x, y, t.w, t.h);   // клик = центр области, сервер получает левый верхний угол
      send({ type: 'use_gadget', item_id: t.itemId, x: o.x, y: o.y, rotated: t.rotated });
      break;
    }
    case 'place_purchased_ship':
      send({ type: 'place_purchased_ship', item_id: t.itemId, x, y, orientation: t.orientation }); break;
  }
}

// ---------- отрисовка экранов ----------
function setState(s) { state = s; stateAt = Date.now(); render(); }

function render() {
  if (!state) { show('menu'); $('#result').classList.add('hidden'); return; }
  if (state.phase === 'lobby') { show('lobby'); renderLobby(); return; }
  show('game');
  renderGame();
}

function renderLobby() {
  $('#lobby-code').textContent = state.lobby;
  const opp = state.opponent;
  $('#lobby-players').innerHTML =
    `<div class="prow">👤 ${esc(state.you.name)} (вы)</div>` +
    `<div class="prow">${opp ? '👤 ' + esc(opp.name) : '⏳ Ожидание второго игрока…'}</div>`;
  const creator = state.you.is_creator;
  $('#btn-start').classList.toggle('hidden', !creator);
  $('#btn-start').disabled = !opp;
  $('#lobby-hint').textContent = creator
    ? (opp ? 'Оба игрока на месте — можно начинать.' : 'Передайте код второму игроку.')
    : 'Ждём, когда создатель начнёт игру.';
}

function renderGame() {
  const you = state.you, opp = state.opponent;
  $('#tb-you').textContent = `${you.name} · очки: ${you.points}`;
  $('#tb-opp').textContent = opp ? `${opp.name} · очки: ${opp.points}` : '';
  $('#tb-code').textContent = `Лобби ${state.lobby}`;
  const st = $('#tb-status');
  const mine = state.phase === 'battle' && state.turn === 'you';
  st.classList.toggle('mine', mine);
  st.textContent = state.phase === 'placement' ? 'Фаза 1 · расстановка'
    : state.phase === 'battle' ? (mine ? 'Ваш ход' : 'Ход соперника') : 'Игра окончена';

  board.setState(state);
  $('#placement-panel').classList.toggle('hidden', state.phase !== 'placement');
  $('#gadget-panel').classList.toggle('hidden', state.phase !== 'battle');
  if (state.phase === 'placement') placement.render(state, orientation);
  if (state.phase === 'battle') gadgets.render(state, orientation, mine);
  board.setTool(currentTool());

  const log = $('#log');
  log.innerHTML = state.log.map(l => `<div class="l-${l.who}">${l.who === 'you' ? 'Вы: ' : l.who === 'opponent' ? 'Соперник: ' : ''}${esc(l.text)}</div>`).join('');
  log.scrollTop = log.scrollHeight;

  updateBanner();
  renderResult();
}

function renderResult() {
  const box = $('#result');
  if (state.phase !== 'finished') { box.classList.add('hidden'); return; }
  const w = state.winner, r = state.finish_reason;
  $('#result-title').textContent = w === 'you' ? '🏆 Победа!' : w === 'opponent' ? '💥 Поражение' : '🤝 Ничья';
  $('#result-text').textContent =
    r === 'disconnect' ? (w === 'you' ? 'Соперник не вернулся за 60 секунд.' : 'Вы были отключены более 60 секунд.')
    : r === 'left' ? (w === 'you' ? 'Соперник покинул партию.' : 'Вы покинули партию.')
    : r === 'mutual_destruction' ? 'Последние корабли обоих игроков уничтожены одновременно.'
    : w === 'you' ? 'Все корабли соперника уничтожены.' : 'Все ваши корабли уничтожены.';
  $('#result-score').textContent = `Очки: вы — ${state.you.points}, соперник — ${state.opponent ? state.opponent.points : 0}`;
  box.classList.remove('hidden');
}

// Баннер «ожидание переподключения» с обратным отсчётом
function updateBanner() {
  const b = $('#opp-banner'), opp = state && state.opponent;
  if (state && state.phase !== 'finished' && state.phase !== 'lobby' && opp && !opp.connected) {
    const left = Math.max(0, opp.reconnect_seconds - Math.floor((Date.now() - stateAt) / 1000));
    b.textContent = `Соперник отключился. Ожидание переподключения: ${left} с`;
    b.classList.remove('hidden');
  } else b.classList.add('hidden');
}
setInterval(updateBanner, 500);

function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

// ---------- кнопки ----------
$('#btn-start').onclick = () => send({ type: 'start_game' });
$('#btn-lobby-leave').onclick = backToMenu;
$('#btn-menu').onclick = backToMenu;
function backToMenu() {
  ws.send({ type: 'leave' });
  ws.clearSession();
  state = null;
  render();
}

// ---------- сообщения сервера ----------
ws.on('_status', ok => $('#conn-banner').classList.toggle('hidden', ok));
ws.on('lobby_created', m => { ws.saveSession(m.code, m.token); setState(m.state); });
ws.on('lobby_joined', m => { ws.saveSession(m.code, m.token); setState(m.state); });
ws.on('opponent_joined', m => { setState(m.state); toast(`${m.name} подключился`, 'good'); });
ws.on('state_update', m => setState(m.state));
ws.on('shot_result', m => {
  board.flash(m.cells.map(c => [c.x, c.y]), m.hit ? '#ff5d5d' : '#9fc3e8');
  const who = m.by === 'you' ? 'Вы' : 'Соперник';
  const hits = m.cells.filter(c => c.result !== 'miss').length;
  let text = hits ? `${who}: попаданий ${hits}${m.sunk.length ? `, потоплено ${m.sunk.length}` : ''}` : `${who}: промах`;
  if (m.by === 'you' && m.gained) text += ` (+${m.gained})`;
  toast(text, m.by === 'you' && hits ? 'good' : 'info');
});
ws.on('error', m => {
  if (m.code === 'reconnect_failed') { ws.clearSession(); state = null; render(); return; }
  toast(m.message, 'error');
  if (m.code === 'lobby_closed') { ws.clearSession(); state = null; render(); }
});

render();
ws.connect();
setTimeout(() => board.fit(), 50);   // сразу показать поле целиком
