(() => {
  'use strict';
  const key = 'diagnostic-recording';
  const rate = .085;
  const policyNames = { both: 'Oba oka', hold: 'Oba oka uz kratke prekide', any: 'Jedno oko je dovoljno (probno)' };
  const clock = seconds => Math.floor(Math.max(0, seconds) / 60).toString().padStart(2, '0') + ':' + Math.floor(Math.max(0, seconds) % 60).toString().padStart(2, '0');
  const date = value => new Intl.DateTimeFormat('bs-BA', { dateStyle: 'short', timeStyle: 'short', timeZone: 'Europe/Sarajevo' }).format(new Date(value));
  function read() { return ReferenceDesign.readSession(key, { active: null, items: [] }); }
  function write(state) {
    ReferenceDesign.writeSession(key, state);
    window.dispatchEvent(new Event('reference-recording-change'));
  }
  function sample(kind = 'completed') {
    const sizeLimit = kind === 'size-limit';
    const seconds = sizeLimit ? 376 : kind === 'interrupted' ? 46 : kind === 'write-error' ? 17 : 120;
    const policy = ReferenceDesign.readSession('eye-policy', 'both');
    return {
      id: 'snimak-' + kind, started: Date.parse('2026-10-22T14:32:00+02:00'),
      seconds, size: sizeLimit ? 32 : Number((seconds * rate).toFixed(1)),
      policy, reason: kind, dropped: kind === 'dropped' ? 23 : 0,
      readable: kind !== 'unreadable',
    };
  }
  function finish(reason = 'manual') {
    const state = read();
    if (!state.active) return;
    const active = state.active;
    const seconds = Math.max(0, Math.min(((active.stopped || Date.now()) - active.started) / 1000, active.minutes * 60, 32 / rate));
    const item = { id: active.id, started: active.started, seconds, size: Math.min(32, seconds * rate), policy: active.policy, reason, dropped: 0, readable: true };
    state.active = null;
    state.items = [item, ...state.items.filter(entry => entry.id !== item.id)].slice(0, 5);
    state.finished = Date.now();
    write(state);
  }
  function state() {
    const value = read();
    if (value.active) {
      if (value.active.stoppingUntil) {
        if (Date.now() >= value.active.stoppingUntil) { finish('manual'); return read(); }
        return value;
      }
      const seconds = (Date.now() - value.active.started) / 1000;
      if (seconds >= Math.min(value.active.minutes * 60, 32 / rate)) {
        finish(seconds * rate >= 32 ? 'size-limit' : 'completed');
        return read();
      }
    }
    return value;
  }
  function start(minutes) {
    const value = state();
    if (value.active) return;
    const started = Date.now();
    value.active = { id: 'snimak-' + started.toString(16), started, minutes, policy: ReferenceDesign.readSession('eye-policy', 'both') };
    value.finished = null;
    write(value);
  }
  function stop() {
    const value = state();
    if (!value.active || value.active.stoppingUntil) return;
    value.active.stopped = Date.now();
    value.active.stoppingUntil = Date.now() + 700;
    write(value);
  }
  function preview(kind) {
    const value = { active: null, items: [], finished: null };
    if (kind === 'recording' || kind === 'finishing') {
      value.active = { id: 'snimak-proba', started: Date.now() - 18000, minutes: 2, policy: ReferenceDesign.readSession('eye-policy', 'both') };
      if (kind === 'finishing') { value.active.stopped = Date.now(); value.active.stoppingUntil = Date.now() + 15000; }
    } else if (!['ready', 'empty'].includes(kind)) value.items = [sample(kind === 'export-error' ? 'completed' : kind)];
    if (kind !== 'empty') value.items.push({ ...sample('completed'), id: 'snimak-raniji', started: Date.parse('2026-10-21T17:45:00+02:00') });
    write(value);
  }
  function renderBadges() {
    const value = state();
    const recent = value.finished && Date.now() - value.finished < 5000;
    for (const badge of document.querySelectorAll('[data-recording-status]')) {
      badge.hidden = !value.active && !recent;
      badge.textContent = value.active?.stoppingUntil ? '● …' : value.active ? '● ' + clock(value.active.minutes * 60 - (Date.now() - value.active.started) / 1000) : 'Snimak završen';
      badge.dataset.finished = String(!value.active);
      badge.title = 'Dijagnostičko snimanje. Za pregled ili ranije zaustavljanje otvorite Postavke → Dijagnostičko snimanje.';
    }
  }
  const query = new URLSearchParams(location.search);
  if (query.get('recording') === 'demo' && !state().active) preview('recording');
  window.ReferenceRecording = Object.freeze({ state, start, stop, preview, clock, date, policy: value => policyNames[value] || 'Nepoznato' });
  window.addEventListener('reference-recording-change', renderBadges);
  window.setInterval(renderBadges, 1000);
  renderBadges();
})();
