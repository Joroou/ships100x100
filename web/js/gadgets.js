// Боковое меню гаджетов: покупка (только в свой ход, если хватает очков) и применение из инвентаря.
const LABEL = {
  scan: i => `Разведка ${i.w}×${i.h}`,
  area_shot: i => `Выстрел ${i.w}×${i.h}`,
  ship: i => `Корабль ${i.w}×${i.h}`,
};

export class GadgetPanel {
  constructor(root, { onBuy, onChange, onRotate }) {
    this.root = root;
    this.cb = { onBuy, onChange, onRotate };
    this.sel = null;          // id выбранного предмета инвентаря
    this.known = null;        // id уже виденных предметов (чтобы автоматически выбрать только что купленный)
    this.items = [];
    this.config = null;
    this.canAct = false;
    this.points = 0;
    this.orientation = 'h';
  }

  build(config) {
    this.config = config;
    const g = config.gadgets;
    const hints = {
      scan: 'Рассеивает туман в области: она видна обоим игрокам, и все корабли в ней (и ваши, и чужие) видны обоим. Клик по полю — центр области.',
      area_shot: 'Обстрел всех клеток области. Клик — центр области. Попадание сохраняет ход.',
      ship: 'Поставьте новый корабль на свободное место. Если там корабль соперника — потонут оба.',
    };
    const opts = kind => g[kind].shapes
      .map((s, idx) => `<option value="${idx}">${s.w}×${s.h} — ${s.price} оч.</option>`).join('');
    this.root.innerHTML = `
      <h3>Гаджеты</h3>
      <div>Очки: <b id="g-points">0</b></div>
      ${['scan', 'area_shot', 'ship'].map(k => `
        <div class="gblock"><h4>${g[k].title}</h4><p class="hint">${hints[k]}</p>
          <div class="row"><select data-kind="${k}" aria-label="${g[k].title}">${opts(k)}</select>
          <button data-buy="${k}">Купить</button></div></div>`).join('')}
      <div class="gblock"><h4>Инвентарь</h4><div class="inv" id="g-inv"></div>
        <p class="hint" id="g-hint"></p>
        <div class="row"><button data-act="rotate" id="g-rot" class="hidden">Повернуть (R)</button>
        <button data-act="cancel" id="g-cancel" class="hidden">Отмена выбора</button></div></div>`;
    this.pts = this.root.querySelector('#g-points');
    this.inv = this.root.querySelector('#g-inv');
    this.hint = this.root.querySelector('#g-hint');
    this.root.addEventListener('change', () => this.refreshButtons());
    this.root.addEventListener('click', e => {
      const b = e.target.closest('button');
      if (!b || b.disabled) return;
      if (b.dataset.buy) {
        const kind = b.dataset.buy;
        const idx = Number(this.root.querySelector(`select[data-kind="${kind}"]`).value);
        const shape = this.config.gadgets[kind].shapes[idx];
        this.cb.onBuy(kind, shape.w, shape.h);
      } else if (b.dataset.item) {
        const id = Number(b.dataset.item);
        this.sel = this.sel === id ? null : id;
        this.update(); this.cb.onChange();
      } else if (b.dataset.act === 'cancel') { this.sel = null; this.update(); this.cb.onChange(); }
      else if (b.dataset.act === 'rotate') this.cb.onRotate();
    });
  }

  render(state, orientation, canAct) {
    if (!this.config) this.build(state.config);
    this.orientation = orientation;
    this.canAct = canAct;
    this.points = state.you.points;
    const items = state.you.inventory;
    // Новый предмет (только что купленный) выбираем автоматически
    if (this.known === null) this.known = new Set(items.map(i => i.id));
    for (const it of items) if (!this.known.has(it.id)) { this.known.add(it.id); this.sel = it.id; }
    if (!items.some(i => i.id === this.sel)) this.sel = null;
    this.items = items;
    this.update();
  }

  update() {
    this.pts.textContent = this.points;
    this.inv.innerHTML = this.items.length
      ? this.items.map(i => `<button class="inv-item ${i.id === this.sel ? 'active' : ''}" data-item="${i.id}">${LABEL[i.kind](i)}</button>`).join('')
      : '<span class="hint">Пусто</span>';
    const item = this.items.find(i => i.id === this.sel);
    // Поворачивать можно и корабли, и области
    this.root.querySelector('#g-rot').classList.toggle('hidden', !item);
    this.root.querySelector('#g-cancel').classList.toggle('hidden', !item);
    const t = this.getTool(this.orientation);
    this.hint.textContent = !item ? 'Выберите предмет, чтобы применить его кликом по полю.'
      : item.kind === 'ship' ? `Корабль ${t.w}×${t.h} (ширина×высота). Клик — левый верхний угол. R — повернуть.`
      : `Область ${t.w}×${t.h} (ширина×высота). Клик — центр области. R — повернуть.`;
    this.refreshButtons();
  }

  refreshButtons() {
    for (const btn of this.root.querySelectorAll('button[data-buy]')) {
      const kind = btn.dataset.buy;
      const idx = Number(this.root.querySelector(`select[data-kind="${kind}"]`).value);
      const price = this.config.gadgets[kind].shapes[idx].price;
      btn.disabled = !this.canAct || price > this.points;
      btn.title = !this.canAct ? 'Покупать можно только в свой ход' : price > this.points ? 'Не хватает очков' : '';
    }
  }

  // Инструмент для поля с учётом поворота (R)
  getTool(orientation) {
    const it = this.items.find(i => i.id === this.sel);
    if (!it) return null;
    if (it.kind === 'ship') {   // w — толщина, h — длина; 'h' = длина вдоль X (как на сервере)
      const horiz = orientation === 'h';
      return { kind: 'rect', w: horiz ? it.h : it.w, h: horiz ? it.w : it.h,
               action: 'place_purchased_ship', itemId: it.id, orientation };
    }
    const rot = orientation === 'v';   // область: 'v' — ширина и высота поменяны местами
    return { kind: 'area', w: rot ? it.h : it.w, h: rot ? it.w : it.h,
             action: 'use_gadget', itemId: it.id, rotated: rot };
  }
}
