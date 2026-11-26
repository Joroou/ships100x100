// Отрисовка поля 100×100 на Canvas с виртуализацией: рисуются только видимые клетки.
// Масштаб — колесом мыши / кнопками, сдвиг — перетаскиванием.
export const N = 100;

// Левый верхний угол области w×h так, чтобы курсор был в её центре, а область не вылезала за поле
export function areaOrigin(x, y, w, h) {
  return {
    x: Math.min(N - w, Math.max(0, x - Math.floor(w / 2))),
    y: Math.min(N - h, Math.max(0, y - Math.floor(h / 2))),
  };
}

export class BoardView {
  constructor(canvas, { onClick, onHover }) {
    this.cv = canvas;
    this.ctx = canvas.getContext('2d');
    this.onClick = onClick;
    this.onHover = onHover;
    this.cs = 14;               // размер клетки в CSS-пикселях
    this.ox = 30; this.oy = 22; // смещение поля
    this.w = 300; this.h = 300; this.dpr = 1;
    // Слои состояния (плоские массивы N*N — быстрый доступ при отрисовке)
    this.mark = new Uint8Array(N * N);   // 1 промах, 2 попадание, 3 потоплено/уничтожено
    this.own = new Uint8Array(N * N);    // 1 — мой живой корабль
    this.fog = new Uint8Array(N * N);    // бит 1 — разведано мной, бит 2 — разведано соперником
    this.seen = new Uint8Array(N * N);   // 1 — живой корабль соперника в моей разведанной области
    this.fogOn = false;                  // туман рисуется только в фазе боя
    this.reveal = new Uint8Array(N * N); // 1 — раскрытый после игры корабль соперника
    this.tool = null;     // {kind:'single'|'area'|'line', size, orientation} — предпросмотр под курсором
    this.hover = null;
    this.flashes = new Map();
    this.raf = 0;
    this.drag = null;
    this.bind();
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
  }

  // ---------- состояние ----------
  setState(state) {
    this.mark.fill(0); this.own.fill(0); this.fog.fill(0); this.seen.fill(0); this.reveal.fill(0);
    const m = state.marks;
    m.miss.forEach(i => { this.mark[i] = 1; });
    m.hit.forEach(i => { this.mark[i] = 2; });
    m.dead.forEach(i => { this.mark[i] = 3; });
    for (const s of state.you.ships) {
      if (s.status !== 'active') continue;
      for (const [x, y] of s.cells) this.own[y * N + x] = 1;
    }
    // Туман войны: разведанные области приходят прямоугольниками
    this.fogOn = state.phase === 'battle';
    const paint = (rects, bit) => {
      for (const [rx, ry, rw, rh] of rects)
        for (let y = ry; y < ry + rh; y++) for (let x = rx; x < rx + rw; x++) this.fog[y * N + x] |= bit;
    };
    paint(state.fog.mine, 1);
    paint(state.fog.opp, 2);
    state.fog.seen.forEach(i => { this.seen[i] = 1; });
    state.reveal.forEach(i => { this.reveal[i] = 1; });
    this.requestDraw();
  }

  setTool(tool) { this.tool = tool; this.requestDraw(); }

  flash(cells, color) {
    const until = performance.now() + 800;
    cells.forEach(([x, y]) => this.flashes.set(y * N + x, { until, color }));
    this.requestDraw();
  }

  // ---------- вид: масштаб и сдвиг ----------
  resize() {
    const r = this.cv.parentElement.getBoundingClientRect();
    this.w = Math.max(1, Math.floor(r.width));
    this.h = Math.max(1, Math.floor(r.height));
    this.dpr = window.devicePixelRatio || 1;
    this.cv.width = Math.floor(this.w * this.dpr);
    this.cv.height = Math.floor(this.h * this.dpr);
    this.clamp();
    this.requestDraw();
  }

  clamp() {
    const W = N * this.cs, m = 60;
    const fix = (o, view) => (W + 2 * m <= view) ? (view - W) / 2 : Math.min(m, Math.max(view - W - m, o));
    this.ox = fix(this.ox, this.w);
    this.oy = fix(this.oy, this.h);
  }

  zoomAt(factor, px = this.w / 2, py = this.h / 2) {
    const ncs = Math.min(40, Math.max(3, this.cs * factor));
    const wx = (px - this.ox) / this.cs, wy = (py - this.oy) / this.cs;
    this.cs = ncs;
    this.ox = px - wx * ncs; this.oy = py - wy * ncs;
    this.clamp(); this.requestDraw();
  }

  fit() {
    this.cs = Math.min(40, Math.max(3, Math.min(this.w - 40, this.h - 40) / N));
    this.ox = (this.w - N * this.cs) / 2; this.oy = (this.h - N * this.cs) / 2;
    this.clamp(); this.requestDraw();
  }

  cellAt(e) {
    const r = this.cv.getBoundingClientRect();
    const x = Math.floor((e.clientX - r.left - this.ox) / this.cs);
    const y = Math.floor((e.clientY - r.top - this.oy) / this.cs);
    return (x >= 0 && y >= 0 && x < N && y < N) ? { x, y } : null;
  }

  bind() {
    const cv = this.cv;
    cv.addEventListener('pointerdown', e => {
      cv.setPointerCapture(e.pointerId);
      this.drag = { x: e.clientX, y: e.clientY, ox: this.ox, oy: this.oy, moved: false };
    });
    cv.addEventListener('pointermove', e => {
      const d = this.drag;
      if (d) {
        const dx = e.clientX - d.x, dy = e.clientY - d.y;
        if (!d.moved && Math.hypot(dx, dy) > 5) d.moved = true;   // отличаем клик от перетаскивания
        if (d.moved) { this.ox = d.ox + dx; this.oy = d.oy + dy; this.clamp(); }
      }
      this.hover = this.cellAt(e);
      this.onHover(this.hover);
      this.requestDraw();
    });
    cv.addEventListener('pointerup', e => {
      const d = this.drag; this.drag = null;
      if (d && !d.moved) {
        const c = this.cellAt(e);
        if (c) this.onClick(c.x, c.y);
      }
    });
    cv.addEventListener('pointerleave', () => { this.hover = null; this.onHover(null); this.requestDraw(); });
    cv.addEventListener('wheel', e => {
      e.preventDefault();
      const r = cv.getBoundingClientRect();
      this.zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
  }

  // ---------- отрисовка ----------
  requestDraw() {
    if (this.raf) return;
    this.raf = requestAnimationFrame(() => { this.raf = 0; this.draw(); });
  }

  cross(px, py, color, lw) {
    const { ctx, cs } = this, m = cs * 0.2;
    ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.beginPath();
    ctx.moveTo(px + m, py + m); ctx.lineTo(px + cs - m, py + cs - m);
    ctx.moveTo(px + cs - m, py + m); ctx.lineTo(px + m, py + cs - m);
    ctx.stroke();
  }

  previewCells() {
    const t = this.tool, h = this.hover;
    if (!t || !h) return null;
    const raw = [];
    if (t.kind === 'single') raw.push([h.x, h.y]);
    else if (t.kind === 'area') {   // область: курсор в центре, у края сдвигается внутрь поля
      const o = areaOrigin(h.x, h.y, t.w, t.h);
      for (let dy = 0; dy < t.h; dy++) for (let dx = 0; dx < t.w; dx++) raw.push([o.x + dx, o.y + dy]);
    } else {                        // 'rect' — корабль: курсор в левом верхнем углу
      for (let dy = 0; dy < t.h; dy++) for (let dx = 0; dx < t.w; dx++) raw.push([h.x + dx, h.y + dy]);
    }
    const inb = ([x, y]) => x >= 0 && y >= 0 && x < N && y < N;
    return { cells: raw.filter(inb), ok: raw.every(inb) };
  }

  draw() {
    const { ctx, cs, w, h } = this;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = '#071322'; ctx.fillRect(0, 0, w, h);
    const x0 = Math.max(0, Math.floor(-this.ox / cs)), x1 = Math.min(N - 1, Math.floor((w - this.ox) / cs));
    const y0 = Math.max(0, Math.floor(-this.oy / cs)), y1 = Math.min(N - 1, Math.floor((h - this.oy) / cs));
    const now = performance.now();
    let animating = false;

    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) {
        const i = y * N + x, px = this.ox + x * cs, py = this.oy + y * cs;
        const mk = this.mark[i];
        let fill = ((x + y) & 1) ? '#12385f' : '#143d68';
        if (this.fogOn) {
          const fg = this.fog[i];
          if (!fg) fill = ((x + y) & 1) ? '#091a2d' : '#0a1d33';              // туман
          else if (!(fg & 1)) fill = ((x + y) & 1) ? '#1a4a5a' : '#1c4e5f';   // разведано соперником
        }
        if (this.seen[i]) fill = '#b7791f';                                   // вражеский корабль в моей разведке
        if (this.reveal[i]) fill = '#7a2d2d';
        if (this.own[i]) fill = '#2f9e6e';
        if (mk === 3) fill = '#3a3f4b';
        ctx.fillStyle = fill; ctx.fillRect(px, py, cs + 0.5, cs + 0.5);
        if (this.seen[i] && cs >= 9) {
          ctx.fillStyle = '#fff'; ctx.font = `bold ${Math.floor(cs * 0.6)}px sans-serif`;
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('?', px + cs / 2, py + cs / 2);
        }
        if (mk) {
          const color = mk === 2 ? '#ff5d5d' : mk === 3 ? '#cfd6e3' : '#8fb0d0';
          if (cs >= 6) this.cross(px, py, color, Math.max(1.5, cs / 8));
          else { ctx.fillStyle = color; ctx.fillRect(px + cs * 0.25, py + cs * 0.25, cs * 0.5, cs * 0.5); }
        }
        const f = this.flashes.get(i);
        if (f) {
          if (f.until > now) {
            ctx.globalAlpha = (f.until - now) / 800; ctx.fillStyle = f.color;
            ctx.fillRect(px, py, cs, cs); ctx.globalAlpha = 1; animating = true;
          } else this.flashes.delete(i);
        }
      }
    }

    if (cs >= 7) this.drawGrid(x0, x1, y0, y1);

    // Предпросмотр выбранного инструмента под курсором
    const pv = this.previewCells();
    if (pv) {
      ctx.fillStyle = pv.ok ? 'rgba(255,255,255,.3)' : 'rgba(255,70,70,.45)';
      ctx.strokeStyle = pv.ok ? '#fff' : '#ff6b6b'; ctx.lineWidth = 1.5;
      for (const [x, y] of pv.cells) {
        ctx.fillRect(this.ox + x * cs, this.oy + y * cs, cs, cs);
        ctx.strokeRect(this.ox + x * cs + 0.5, this.oy + y * cs + 0.5, cs - 1, cs - 1);
      }
    }

    // Рамка поля
    ctx.strokeStyle = '#7fd1ff'; ctx.lineWidth = 2;
    ctx.strokeRect(this.ox, this.oy, N * cs, N * cs);
    this.drawLabels(x0, x1, y0, y1);
    if (animating) this.requestDraw();
  }

  drawGrid(x0, x1, y0, y1) {
    const { ctx, cs } = this;
    const ya = this.oy + y0 * cs, yb = this.oy + (y1 + 1) * cs;
    const xa = this.ox + x0 * cs, xb = this.ox + (x1 + 1) * cs;
    for (const strong of [false, true]) {
      ctx.strokeStyle = strong ? 'rgba(160,210,255,.45)' : 'rgba(120,170,220,.16)';
      ctx.lineWidth = 1; ctx.beginPath();
      for (let x = x0; x <= x1 + 1; x++) {
        if ((x % 10 === 0) !== strong) continue;
        const px = Math.round(this.ox + x * cs) + 0.5; ctx.moveTo(px, ya); ctx.lineTo(px, yb);
      }
      for (let y = y0; y <= y1 + 1; y++) {
        if ((y % 10 === 0) !== strong) continue;
        const py = Math.round(this.oy + y * cs) + 0.5; ctx.moveTo(xa, py); ctx.lineTo(xb, py);
      }
      ctx.stroke();
    }
  }

  // Подписи координат (с 1) по верхнему и левому краю экрана
  drawLabels(x0, x1, y0, y1) {
    const { ctx, cs } = this;
    const step = cs >= 20 ? 1 : cs >= 10 ? 5 : 10;
    ctx.fillStyle = 'rgba(8,20,36,.82)'; ctx.fillRect(0, 0, this.w, 16); ctx.fillRect(0, 0, 30, this.h);
    ctx.fillStyle = '#9fc3e8'; ctx.font = '10px sans-serif'; ctx.textBaseline = 'middle';
    ctx.textAlign = 'center';
    for (let x = x0; x <= x1; x++) if ((x + 1) % step === 0 || x === 0) ctx.fillText(String(x + 1), this.ox + x * cs + cs / 2, 8);
    ctx.textAlign = 'right';
    for (let y = y0; y <= y1; y++) if ((y + 1) % step === 0 || y === 0) ctx.fillText(String(y + 1), 26, this.oy + y * cs + cs / 2);
  }
}
