/* kuro·console — 共通ヘルパー */

const KURO = {
  GLYPHS: { github: '◆', obsidian: '◇', n8n: '⬡', llm: '✳', browser: '▣' },

  glyph(tool) { return KURO.GLYPHS[tool] || '·'; },

  esc(s) {
    return String(s ?? '')
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;');
  },

  async json(url, opts) {
    const res = await fetch(url, opts);
    if (!res.ok) throw new Error(url + ' -> HTTP ' + res.status);
    return res.json();
  },

  statusText(t) {
    return t === 'running' ? '実行中' : t === 'failed' ? '失敗' : '完了';
  },

  // step の状態 -> バッジ表記（デザイン: exec / run / fail / stub）
  badge(state) {
    return { done: 'exec', run: 'run', failed: 'fail', stub: 'stub', skip: 'skip' }[state] || state;
  },

  fmtDur(s) {
    if (s == null) return '';
    if (s < 60) return s.toFixed(1).replace(/\.0$/, '') + 's';
    return Math.floor(s / 60) + 'm' + String(Math.round(s % 60)).padStart(2, '0') + 's';
  },

  async health() {
    try { return await KURO.json('/api/health'); }
    catch { return { llm_up: false, endpoint_configured: false, running: 0 }; }
  },

  // ヘッダー右側のステータスドット + ラベルを更新する
  applyHealth(h, dotEl, labelEl) {
    const running = h.running > 0;
    dotEl.className = 'dot ' + (running ? 'boot' : h.llm_up ? 'on' : 'idle');
    labelEl.className = 'status-label' + (h.llm_up || running ? '' : ' idle');
    labelEl.textContent = running ? '実行中' : h.llm_up ? '常駐' : '待機';
  },
};
