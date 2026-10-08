// Küçük DOM yardımcıları

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'dataset') Object.assign(node.dataset, v);
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, '');
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

const nf = new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const nf4 = new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 4, minimumFractionDigits: 2 });

export function fmtPrice(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '–';
  return Math.abs(v) < 10 ? nf4.format(v) : nf.format(v);
}

export function fmtNum(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '–';
  const a = Math.abs(v);
  if (a >= 1e9) return `${nf.format(v / 1e9)} Mr`;
  if (a >= 1e6) return `${nf.format(v / 1e6)} Mn`;
  if (a >= 1e4) return `${nf.format(v / 1e3)} B`;
  return fmtPrice(v);
}

export function fmtPct(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '–';
  return `${v > 0 ? '+' : ''}${nf.format(v)}%`;
}

export const pctClass = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : '');

export function fmtTime(iso) {
  if (!iso) return '–';
  return new Date(iso).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' });
}

export function toast(message, isError = false) {
  const t = el('div', { class: `toast${isError ? ' err' : ''}` }, message);
  $('#toasts').append(t);
  setTimeout(() => t.remove(), isError ? 7000 : 5000);
}

// Basit form modalı. fields: [{name, label, type, value, options:[[v,l]]}]
export function modal(title, fields, { okText = 'Tamam', body } = {}) {
  return new Promise((resolve) => {
    const box = $('#modal');
    $('#modal-title').textContent = title;
    const bodyEl = $('#modal-body');
    bodyEl.replaceChildren();
    const inputs = {};
    for (const f of fields) {
      let input;
      if (f.type === 'select') {
        input = el('select', {}, f.options.map(([v, l]) => el('option', { value: v, selected: String(v) === String(f.value) }, l)));
      } else if (f.type === 'checkbox') {
        input = el('input', { type: 'checkbox', checked: !!f.value });
      } else {
        input = el('input', { type: f.type || 'text', value: f.value ?? '', step: f.step || 'any' });
      }
      inputs[f.name] = input;
      bodyEl.append(el('label', { class: 'field' }, f.label, input));
    }
    if (body) bodyEl.append(body);
    $('#modal-ok').textContent = okText;
    $('#modal-ok').classList.toggle('hidden', okText === null);
    box.classList.remove('hidden');
    const first = Object.values(inputs)[0];
    if (first) setTimeout(() => first.focus(), 0);

    const close = (result) => {
      box.classList.add('hidden');
      $('#modal-ok').onclick = $('#modal-cancel').onclick = null;
      box.onkeydown = null;
      resolve(result);
    };
    $('#modal-cancel').onclick = () => close(null);
    $('#modal-ok').onclick = () => {
      const out = {};
      for (const f of fields) {
        const i = inputs[f.name];
        out[f.name] = f.type === 'checkbox' ? i.checked : f.type === 'number' ? parseFloat(i.value) : i.value;
      }
      close(out);
    };
    box.onkeydown = (e) => {
      if (e.key === 'Escape') close(null);
      if (e.key === 'Enter' && e.target.tagName === 'INPUT') $('#modal-ok').click();
    };
  });
}

export const store = {
  get(key, fallback) {
    try {
      const v = localStorage.getItem(key);
      return v === null ? fallback : JSON.parse(v);
    } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* depolama kapalı */ }
  },
};

// Basit olay yayıncısı (modüller arası iletişim)
const listeners = {};
export const bus = {
  on(evt, fn) { (listeners[evt] ||= []).push(fn); },
  emit(evt, data) { (listeners[evt] || []).forEach((fn) => fn(data)); },
};
