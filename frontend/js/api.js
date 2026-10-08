// Backend REST API istemcisi
async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
    } catch { /* gövde JSON değil */ }
    throw new Error(detail);
  }
  return res.json();
}

const qs = (params) => new URLSearchParams(
  Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''),
).toString();

export const api = {
  status: () => request('GET', '/status'),
  runJob: (name, market) => request('POST', `/jobs/${name}`, market ? { market } : {}),

  searchSymbols: (q, limit = 30) => request('GET', `/symbols?${qs({ q, limit })}`),
  symbol: (id) => request('GET', `/symbols/${id}`),
  bars: (symbolId, tf) => request('GET', `/bars?${qs({ symbol_id: symbolId, tf })}`),
  indicatorList: () => request('GET', '/indicators'),
  indicator: (symbolId, tf, name, params) =>
    request('GET', `/indicator?${qs({ symbol_id: symbolId, tf, name, params: JSON.stringify(params || {}) })}`),
  quotes: (ids) => request('GET', `/quotes?ids=${ids.join(',')}`),

  watchlists: () => request('GET', '/watchlists'),
  createWatchlist: (name) => request('POST', '/watchlists', { name }),
  renameWatchlist: (id, name) => request('PATCH', `/watchlists/${id}`, { name }),
  deleteWatchlist: (id) => request('DELETE', `/watchlists/${id}`),
  watchlistItems: (id) => request('GET', `/watchlists/${id}/items`),
  addToWatchlist: (id, symbolId) => request('POST', `/watchlists/${id}/items`, { symbol_id: symbolId }),
  removeFromWatchlist: (id, symbolId) => request('DELETE', `/watchlists/${id}/items/${symbolId}`),
  reorderWatchlist: (id, symbolIds) => request('PUT', `/watchlists/${id}/items`, { symbol_ids: symbolIds }),

  screenerFields: () => request('GET', '/screener/fields'),
  runScreen: (body) => request('POST', '/screener/run', body),

  scans: () => request('GET', '/scans'),
  createScan: (body) => request('POST', '/scans', body),
  updateScan: (id, body) => request('PUT', `/scans/${id}`, body),
  deleteScan: (id) => request('DELETE', `/scans/${id}`),
  runScan: (id) => request('POST', `/scans/${id}/run`),
  scanResults: (id) => request('GET', `/scans/${id}/results`),

  alerts: () => request('GET', '/alerts'),
  createAlert: (body) => request('POST', '/alerts', body),
  updateAlert: (id, body) => request('PUT', `/alerts/${id}`, body),
  deleteAlert: (id) => request('DELETE', `/alerts/${id}`),
  events: (sinceId = 0) => request('GET', `/events?since_id=${sinceId}`),
  markEventsSeen: () => request('POST', '/events/seen'),

  drawings: (symbolId) => request('GET', `/drawings?symbol_id=${symbolId}`),
  createDrawing: (body) => request('POST', '/drawings', body),
  deleteDrawing: (id) => request('DELETE', `/drawings/${id}`),
};
