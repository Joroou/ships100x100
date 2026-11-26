// Стартовый экран: имя, создание лобби, подключение по коду.
const $ = s => document.querySelector(s);
const NAME_KEY = 'seabattle_name';

export class Menu {
  constructor({ onCreate, onJoin, onError }) {
    this.name = $('#name');
    this.code = $('#code');
    try { this.name.value = sessionStorage.getItem(NAME_KEY) || ''; } catch { /* ignore */ }
    this.code.addEventListener('input', () => { this.code.value = this.code.value.toUpperCase().replace(/[^A-Z0-9]/g, ''); });

    $('#btn-create').addEventListener('click', () => onCreate(this.playerName()));
    $('#btn-join').addEventListener('click', () => {
      const code = this.code.value.trim();
      if (code.length !== 6) return onError('Код лобби — 6 символов');
      onJoin(this.playerName(), code);
    });
    $('#btn-shutdown').addEventListener('click', async () => {
      try { await fetch('/api/shutdown', { method: 'POST' }); } catch { /* сервер уже остановился */ }
      document.body.innerHTML = '<p style="padding:24px;color:#e6f0fb">Сервер остановлен. Вкладку можно закрыть.</p>';
    });
    this.loadInfo();
  }

  playerName() {
    const n = this.name.value.trim() || 'Игрок';
    try { sessionStorage.setItem(NAME_KEY, n); } catch { /* ignore */ }
    return n;
  }

  // Адрес для подключения с других устройств показываем только хозяину сервера
  async loadInfo() {
    const isHost = ['127.0.0.1', 'localhost', '[::1]'].includes(location.hostname);
    if (!isHost) { $('#btn-shutdown').classList.add('hidden'); $('#lan-info').textContent = ''; return; }
    try {
      const d = await (await fetch('/api/info')).json();
      if (d.ips && d.ips.length) {
        $('#lan-info').textContent = 'Второй игрок в той же Wi-Fi сети открывает в браузере: ' +
          d.ips.map(ip => `http://${ip}:${d.port}`).join('  или  ') +
          '. Если не открывается, попробуйте другой адрес.';
      }
    } catch { /* не критично */ }
  }
}
