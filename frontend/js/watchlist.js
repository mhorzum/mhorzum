// İzleme listeleri (sağ panel)
import { api } from './api.js';
import { openSymbol, getState } from './chart.js';
import { $, el, fmtPct, fmtPrice, modal, pctClass, store, toast, bus } from './ui.js';

let lists = [];
let currentId = store.get('watchlistId', null);
let items = [];

export async function initWatchlists() {
  $('#wl-select').onchange = (e) => selectList(Number(e.target.value));
  $('#wl-new').onclick = newList;
  $('#wl-rename').onclick = renameList;
  $('#wl-delete').onclick = deleteList;
  $('#wl-add-symbol').onclick = () => {
    const s = getState().symbol;
    if (s) addSymbol(s.id);
  };
  bus.on('symbol:changed', highlight);
  await loadLists();
  setInterval(refreshItems, 30000);
}

export const getLists = () => lists;

async function loadLists() {
  lists = await api.watchlists();
  if (!lists.length) {
    await api.createWatchlist('Favoriler');
    lists = await api.watchlists();
  }
  if (!lists.some((l) => l.id === currentId)) currentId = lists[0].id;
  const sel = $('#wl-select');
  sel.replaceChildren(...lists.map((l) => el('option', { value: l.id, selected: l.id === currentId }, `${l.name} (${l.count})`)));
  bus.emit('watchlists:changed', lists);
  await refreshItems();
}

async function selectList(id) {
  currentId = id;
  store.set('watchlistId', id);
  await refreshItems();
}

export async function addSymbol(symbolId, listId = currentId) {
  try {
    await api.addToWatchlist(listId, symbolId);
    await loadLists();
  } catch (e) { toast(e.message, true); }
}

async function newList() {
  const res = await modal('Yeni izleme listesi', [{ name: 'name', label: 'Ad', value: '' }]);
  if (!res?.name) return;
  const wl = await api.createWatchlist(res.name);
  currentId = wl.id;
  store.set('watchlistId', wl.id);
  await loadLists();
}

async function renameList() {
  const wl = lists.find((l) => l.id === currentId);
  const res = await modal('Listeyi yeniden adlandır', [{ name: 'name', label: 'Ad', value: wl.name }]);
  if (!res?.name) return;
  await api.renameWatchlist(currentId, res.name);
  await loadLists();
}

async function deleteList() {
  const wl = lists.find((l) => l.id === currentId);
  const ok = await modal(`"${wl.name}" listesi silinsin mi?`, [], { okText: 'Sil' });
  if (!ok) return;
  await api.deleteWatchlist(currentId);
  currentId = null;
  await loadLists();
}

async function refreshItems() {
  if (!currentId) return;
  try {
    items = await api.watchlistItems(currentId);
  } catch { return; }
  render();
}

let dragId = null;

function render() {
  const ul = $('#wl-items');
  const cur = getState().symbol?.id;
  ul.replaceChildren(...items.map((it) => {
    const li = el('li', {
      draggable: 'true',
      class: it.symbol_id === cur ? 'current' : '',
      dataset: { id: it.symbol_id },
      onclick: () => openSymbol(it.symbol_id).catch((e) => toast(e.message, true)),
      ondragstart: () => { dragId = it.symbol_id; },
      ondragover: (e) => { e.preventDefault(); li.classList.add('drag-over'); },
      ondragleave: () => li.classList.remove('drag-over'),
      ondrop: (e) => { e.preventDefault(); li.classList.remove('drag-over'); reorder(dragId, it.symbol_id); },
    },
    el('span', { class: 't', title: it.name || '' }, it.ticker, el('small', {}, `${it.market === 'BIST' ? 'BIST' : it.exchange}${it.live ? ' · canlı' : ''}`)),
    el('span', { class: 'p' }, fmtPrice(it.price)),
    el('span', { class: `c ${pctClass(it.change_pct)}` }, fmtPct(it.change_pct)),
    el('button', {
      class: 'x', title: 'Listeden çıkar',
      onclick: async (e) => {
        e.stopPropagation();
        await api.removeFromWatchlist(currentId, it.symbol_id);
        await loadLists();
      },
    }, '×'));
    return li;
  }));
  if (!items.length) {
    ul.append(el('li', { class: 'muted' }, 'Liste boş. Grafikteki sembolü ＋ ile ekleyin.'));
  }
}

async function reorder(fromId, toId) {
  if (!fromId || fromId === toId) return;
  const ids = items.map((i) => i.symbol_id).filter((id) => id !== fromId);
  ids.splice(ids.indexOf(toId), 0, fromId);
  items.sort((a, b) => ids.indexOf(a.symbol_id) - ids.indexOf(b.symbol_id));
  render();
  await api.reorderWatchlist(currentId, ids);
}

function highlight(symbol) {
  for (const li of $('#wl-items').children) li.classList.toggle('current', Number(li.dataset.id) === symbol.id);
}
