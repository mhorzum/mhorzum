// Uygulama girişi: arama, durum çubuğu, sekmeler
import { api } from './api.js';
import { initAlerts } from './alerts.js';
import { initChart, openSymbol } from './chart.js';
import { initScreener, loadScans } from './screener.js';
import { $, $$, el, store, toast } from './ui.js';
import { initWatchlists } from './watchlist.js';

function initTabs() {
  for (const tab of $$('.tab')) {
    tab.onclick = () => {
      for (const t of $$('.tab')) t.classList.toggle('active', t === tab);
      for (const body of $$('.tab-body')) body.classList.toggle('hidden', body.id !== `tab-${tab.dataset.tab}`);
      $('.layout').classList.remove('collapsed');
      if (tab.dataset.tab === 'scans') loadScans();
    };
  }
  const layout = $('.layout');
  layout.classList.toggle('collapsed', store.get('bottomCollapsed', false));
  $('#bottom-toggle').onclick = () => {
    layout.classList.toggle('collapsed');
    store.set('bottomCollapsed', layout.classList.contains('collapsed'));
  };
}

function initSearch() {
  const input = $('#symbol-search');
  const box = $('#search-results');
  let timer;
  let results = [];
  let sel = 0;

  const render = () => {
    box.replaceChildren(...results.map((s, i) => el('div', {
      class: `item${i === sel ? ' sel' : ''}`,
      onmousedown: (e) => { e.preventDefault(); choose(s); },
    }, el('b', {}, s.ticker), el('small', {}, s.name || ''), el('span', { class: 'mk' }, s.market === 'BIST' ? 'BIST' : s.exchange))));
    box.classList.toggle('hidden', !results.length);
  };
  const choose = (s) => {
    input.value = '';
    results = [];
    render();
    input.blur();
    openSymbol(s.id).catch((e) => toast(e.message, true));
  };
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      results = q ? await api.searchSymbols(q, 15).catch(() => []) : [];
      sel = 0;
      render();
    }, 150);
  };
  input.onkeydown = (e) => {
    if (e.key === 'ArrowDown') { sel = Math.min(sel + 1, results.length - 1); render(); e.preventDefault(); }
    if (e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); render(); e.preventDefault(); }
    if (e.key === 'Enter' && results[sel]) choose(results[sel]);
    if (e.key === 'Escape') { results = []; render(); input.blur(); }
  };
  input.onblur = () => setTimeout(() => box.classList.add('hidden'), 150);
  // Herhangi bir yerde harf yazınca aramaya odaklan (TradingView gibi)
  document.addEventListener('keydown', (e) => {
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || e.ctrlKey || e.metaKey || e.altKey) return;
    if (/^[a-zA-Z0-9]$/.test(e.key) && $('#modal').classList.contains('hidden')) input.focus();
  });
}

function initDataMenu() {
  const menu = $('#data-menu');
  $('#btn-data').onclick = (e) => { e.stopPropagation(); menu.classList.toggle('hidden'); };
  document.addEventListener('click', (e) => { if (!menu.contains(e.target)) menu.classList.add('hidden'); });
  for (const b of menu.querySelectorAll('button')) {
    b.onclick = async () => {
      menu.classList.add('hidden');
      try {
        await api.runJob(b.dataset.job, b.dataset.market);
        toast(`Başlatıldı: ${b.textContent}`);
        setTimeout(refreshStatus, 1500);
      } catch (e) { toast(e.message, true); }
    };
  }
}

const JOB_NAMES = {
  sync_universe: 'Sembol listesi', backfill_ALL: 'Geçmiş veri', backfill_BIST: 'BIST geçmiş', backfill_US: 'ABD geçmiş',
  update_BIST: 'BIST güncelleme', update_US: 'ABD güncelleme',
};

async function refreshStatus() {
  let s;
  try { s = await api.status(); } catch { return; }
  const box = $('#status');
  const parts = Object.entries(s.markets).map(([code, m]) => el('span', {
    title: `Son günlük bar: ${s.last_bar[code] || '–'} · ${s.symbols[code]?.total || 0} sembol`,
  }, el('span', { class: `dot${m.open ? ' open' : ''}` }), `${code === 'US' ? 'ABD' : code} ${m.open ? 'açık' : 'kapalı'}`));
  for (const [job, p] of Object.entries(s.progress)) {
    parts.push(el('span', { class: 'job' }, `⟳ ${JOB_NAMES[job] || job} ${p.done}/${p.total}`));
  }
  const failed = s.jobs.filter((j) => j.status === 'error');
  if (failed.length) {
    parts.push(el('span', { class: 'down', title: failed.map((j) => `${j.job}: ${j.message}`).join('\n') }, `⚠ ${failed.length} iş hatası`));
  }
  if (s.provider === 'demo') parts.push(el('span', { class: 'job', title: 'DATA_PROVIDER=demo: sentetik veri' }, 'DEMO VERİ'));
  box.replaceChildren(...parts);
}

async function main() {
  initTabs();
  initSearch();
  initDataMenu();
  await initChart();
  await initWatchlists();
  await initScreener();
  await initAlerts();
  refreshStatus();
  setInterval(refreshStatus, 15000);
}

main().catch((e) => toast(`Başlatma hatası: ${e.message}`, true));
