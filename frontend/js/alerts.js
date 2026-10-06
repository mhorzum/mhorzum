// Alarmlar ve bildirimler
import { api } from './api.js';
import { getState, openSymbol, TF_LABELS } from './chart.js';
import { $, el, fmtPrice, fmtTime, toast, bus } from './ui.js';

let lists = [];
let lastEventId = 0;
let unseen = 0;

export async function initAlerts() {
  $('#al-tf').replaceChildren(...Object.entries(TF_LABELS).map(([tf, l]) => el('option', { value: tf, selected: tf === '1d' }, l)));
  $('#al-kind').onchange = syncForm;
  $('#alert-form').onsubmit = submit;
  $('#btn-alert').onclick = () => {
    document.querySelector('.tab[data-tab="alerts"]').click();
    prefill();
    $('#al-value').focus();
  };
  bus.on('symbol:changed', prefill);
  bus.on('watchlists:changed', (l) => { lists = l; fillTargets(); });
  syncForm();
  await loadAlerts();

  $('#ev-notify').onclick = async () => {
    if (!('Notification' in window)) return toast('Tarayıcı bildirimleri desteklenmiyor', true);
    const p = await Notification.requestPermission();
    toast(p === 'granted' ? 'Tarayıcı bildirimleri açık' : 'İzin verilmedi');
  };
  $('#ev-seen').onclick = async () => { await api.markEventsSeen(); unseen = 0; updateBadge(); await loadEvents(true); };
  await loadEvents(true);
  setInterval(() => loadEvents(false), 20000);
}

function syncForm() {
  const price = $('#al-kind').value === 'price';
  $('.al-price').classList.toggle('hidden', !price);
  $('.al-expr').classList.toggle('hidden', price);
  $('#al-value').required = price;
  fillTargets();
}

function fillTargets() {
  const sel = $('#al-target');
  const s = getState().symbol;
  const opts = [];
  if (s) opts.push(el('option', { value: `s:${s.id}` }, `${s.ticker} (grafikteki sembol)`));
  if ($('#al-kind').value === 'expression') {
    for (const l of lists) opts.push(el('option', { value: `w:${l.id}` }, `Liste: ${l.name}`));
  }
  sel.replaceChildren(...opts);
}

function prefill() {
  fillTargets();
  const { lastClose, symbol } = getState();
  if (symbol && lastClose) $('#al-value').value = +lastClose.toFixed(lastClose < 10 ? 4 : 2);
}

async function submit(e) {
  e.preventDefault();
  const msg = $('#al-msg');
  const target = $('#al-target').value;
  if (!target) { msg.textContent = 'Önce bir sembol açın'; msg.className = 'msg err'; return; }
  const [t, id] = target.split(':');
  const kind = $('#al-kind').value;
  const body = {
    kind,
    symbol_id: t === 's' ? Number(id) : null,
    watchlist_id: t === 'w' ? Number(id) : null,
    mode: $('#al-mode').value,
    note: $('#al-note').value || null,
  };
  if (kind === 'price') {
    body.operator = $('#al-op').value;
    body.value = parseFloat($('#al-value').value);
  } else {
    body.expression = $('#al-expr').value;
    body.timeframe = $('#al-tf').value;
  }
  try {
    await api.createAlert(body);
    msg.className = 'msg';
    msg.textContent = 'Alarm eklendi';
    $('#al-note').value = '';
    await loadAlerts();
    bus.emit('alerts:changed');
  } catch (err) {
    msg.className = 'msg err';
    msg.textContent = err.message;
  }
}

async function loadAlerts() {
  const alerts = await api.alerts();
  const table = $('#alerts-table');
  const describe = (a) => (a.kind === 'price'
    ? `Fiyat ${a.operator === 'cross_up' ? 'yukarı keserse' : 'aşağı keserse'} ${fmtPrice(a.value)}`
    : `[${TF_LABELS[a.timeframe]}] ${a.expression}`);
  table.replaceChildren(
    el('thead', {}, el('tr', {}, ...['Hedef', 'Koşul', 'Tekrar', 'Not', 'Son tetiklenme', 'Durum', ''].map((h, i) =>
      el('th', { class: i < 2 || i === 3 ? 'l' : '' }, h)))),
    el('tbody', {}, alerts.map((a) => el('tr', {},
      el('td', {
        class: 'l',
        onclick: () => a.symbol_id && openSymbol(a.symbol_id),
      }, a.ticker ? el('b', {}, a.ticker) : `Liste: ${a.watchlist_name || '?'}`),
      el('td', { class: 'expr-cell', title: describe(a) }, describe(a)),
      el('td', {}, a.mode === 'once' ? 'Bir kez' : 'Her seferinde'),
      el('td', { class: 'l muted' }, a.note || ''),
      el('td', {}, fmtTime(a.last_triggered_at)),
      el('td', { class: a.active ? 'up' : 'muted' }, a.active ? 'Aktif' : 'Pasif'),
      el('td', {},
        el('button', { class: 'btn', onclick: () => toggle(a) }, a.active ? 'Durdur' : 'Etkinleştir'), ' ',
        el('button', { class: 'btn', onclick: () => remove(a) }, 'Sil')),
    ))),
  );
}

async function toggle(a) {
  await api.updateAlert(a.id, { ...a, active: !a.active });
  await loadAlerts();
  bus.emit('alerts:changed');
}

async function remove(a) {
  await api.deleteAlert(a.id);
  await loadAlerts();
  bus.emit('alerts:changed');
}

async function loadEvents(initial) {
  let events;
  try {
    events = await api.events(initial ? 0 : lastEventId);
  } catch { return; }
  if (initial) {
    $('#events-list').replaceChildren();
    unseen = events.filter((e) => !e.seen).length;
  } else {
    unseen += events.length;
    for (const ev of [...events].reverse()) {
      toast(ev.message);
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('Borsa Terminali', { body: ev.message });
      }
    }
    if (events.length) await loadAlerts();
  }
  if (events.length) lastEventId = Math.max(lastEventId, ...events.map((e) => e.id));
  const list = $('#events-list');
  if (events.length) list.querySelector('li.muted')?.remove();
  const nodes = events.map((ev) => el('li', { class: ev.seen ? '' : 'unseen' },
    el('time', {}, fmtTime(ev.triggered_at)), ev.message));
  list.prepend(...nodes);
  if (!list.children.length) list.append(el('li', { class: 'muted' }, 'Henüz bildirim yok.'));
  updateBadge();
}

function updateBadge() {
  const b = $('#events-badge');
  b.textContent = unseen;
  b.classList.toggle('hidden', unseen === 0);
}
