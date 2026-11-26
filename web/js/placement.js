// Панель фазы расстановки: выбор корабля (толщина×длина), поворот, кнопка «Готов».
const cells = key => key.split('x').reduce((a, b) => a * b, 1);

export class PlacementPanel {
  constructor(root, { onReady, onRotate, onChange }) {
    this.root = root;
    this.sel = null;   // ключ выбранной формы, например "2x5"
    this.cb = { onReady, onRotate, onChange };
    root.addEventListener('click', e => {
      const btn = e.target.closest('button');
      if (!btn || btn.disabled) return;
      if (btn.dataset.shape) { this.sel = btn.dataset.shape; this.cb.onChange(); }
      else if (btn.dataset.act === 'rotate') this.cb.onRotate();
      else if (btn.dataset.act === 'ready') this.cb.onReady();
    });
  }

  render(state, orientation) {
    const you = state.you, tp = you.to_place || {};
    const keys = Object.keys(tp).sort((a, b) => cells(a) - cells(b));
    if (!keys.includes(this.sel) || !tp[this.sel]) this.sel = keys.find(k => tp[k] > 0) ?? null;
    const opp = state.opponent;
    this.root.innerHTML = `
      <h3>Фаза 1 — расстановка</h3>
      <p class="hint">Выберите корабль (толщина×длина) и кликните по полю: клик — левый верхний угол корабля.
        Соперник ваших кораблей не видит. Если корабли совпадут хотя бы одной клеткой — оба будут уничтожены.</p>
      <div class="ships">${keys.map(k => `
        <button class="ship-btn ${k === this.sel ? 'active' : ''}" data-shape="${k}" ${tp[k] && !you.ready ? '' : 'disabled'}>
          ${k.replace('x', '×')}<span>осталось: ${tp[k]}</span></button>`).join('')}</div>
      <button data-act="rotate">Длина вдоль: ${orientation === 'h' ? 'горизонтали →' : 'вертикали ↓'} (клавиша R)</button>
      <button class="primary" data-act="ready" ${you.ready ? 'disabled' : ''}>${you.ready ? 'Ожидание соперника…' : 'Готов'}</button>
      <p class="hint">Соперник: ${opp ? (opp.ready ? 'готов' : 'расставляет корабли') : '—'}</p>`;
  }

  // Инструмент для поля: прямоугольник w×h (при горизонтали длина идёт по ширине — как на сервере)
  getTool(orientation) {
    if (!this.sel) return null;
    const [t, l] = this.sel.split('x').map(Number);
    const horiz = orientation === 'h';
    return { kind: 'rect', w: horiz ? l : t, h: horiz ? t : l, action: 'place_ship', t, l, orientation };
  }
}
