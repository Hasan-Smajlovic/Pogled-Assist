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
    } else if (!['ready', 'empty'].includes(kind)) {
      value.items = [sample(kind === 'export-error' ? 'completed' : kind)];
      value.finished = Date.now();
    }
    if (kind !== 'empty') value.items.push({ ...sample('completed'), id: 'snimak-raniji', started: Date.parse('2026-10-21T17:45:00+02:00') });
    write(value);
  }
  function badgeState(value) {
    if (value.active?.stoppingUntil) return { kind: 'finishing', text: 'Završavam snimak…', compact: 'Čuvam…' };
    if (value.active) {
      const remaining = clock(Math.ceil(value.active.minutes * 60 - (Date.now() - value.active.started) / 1000));
      return { kind: 'recording', text: 'Snimanje dijagnostike · ' + remaining, compact: remaining };
    }
    if (!value.finished) return null;
    const item = value.items[0];
    if (!item) return null;
    if (item.reason === 'write-error') return { kind: 'error', text: 'Greška čuvanja snimka', compact: 'Greška' };
    if (!item.readable) return { kind: 'error', text: 'Snimak nije čitljiv', compact: 'Nečitljivo' };
    if (!['manual', 'completed'].includes(item.reason)) return { kind: 'incomplete', text: 'Snimak nije potpun', compact: 'Nepotpuno' };
    if (Date.now() - value.finished < 5000) return { kind: 'saved', text: 'Snimak je sačuvan', compact: 'Sačuvano' };
    return null;
  }
  const announcement = document.createElement('p');
  announcement.className = 'recording-announcement';
  announcement.setAttribute('role', 'status');
  announcement.setAttribute('aria-live', 'polite');
  document.body.append(announcement);
  let announced = '';
  function renderBadges() {
    const value = state();
    const status = badgeState(value);
    for (const badge of document.querySelectorAll('[data-recording-status]')) {
      badge.hidden = !status;
      if (!status) continue;
      const text = badge.hasAttribute('data-recording-compact') ? status.compact : status.text;
      if (badge.textContent !== text) badge.textContent = text;
      badge.dataset.state = status.kind;
      badge.setAttribute('aria-label', status.text);
      badge.title = status.text + '. Za pregled ili ranije zaustavljanje otvorite Postavke → Dijagnostičko snimanje.';
    }
    const transition = (value.active?.id || value.items[0]?.id || '') + ':' + (status?.kind || 'idle');
    if (transition !== announced) {
      announced = transition;
      announcement.textContent = status?.kind === 'recording' ? 'Snimanje dijagnostike je u toku.' : status?.text || '';
    }
  }
  function addPreviewControl() {
    const tools = document.querySelector('.reference-tools');
    if (!tools || document.body.dataset.referencePage === 'diagnostics') return;
    const label = document.createElement('label');
    label.textContent = 'Dijagnostičko snimanje ';
    const select = document.createElement('select');
    for (const [value, text] of [
      ['ready', 'Bez snimanja'], ['recording', 'Snimanje u toku'], ['finishing', 'Završavanje snimka'],
      ['completed', 'Snimak je sačuvan'], ['size-limit', 'Dostignut limit prostora'],
      ['dropped', 'Snimak nije potpun'], ['write-error', 'Greška čuvanja'],
    ]) {
      const option = document.createElement('option');
      option.value = value; option.textContent = text; select.append(option);
    }
    const current = state();
    const reason = current.items[0]?.reason;
    select.value = current.active ? current.active.stoppingUntil ? 'finishing' : 'recording'
      : current.finished ? reason === 'manual' ? 'completed' : reason : 'ready';
    if (!select.value) select.value = 'ready';
    select.addEventListener('change', () => preview(select.value));
    label.append(select); tools.append(label);
  }
  const query = new URLSearchParams(location.search);
  if (query.get('recording') === 'demo' && !state().active) preview('recording');
  window.ReferenceRecording = Object.freeze({ state, start, stop, preview, clock, date, policy: value => policyNames[value] || 'Nepoznato' });
  window.addEventListener('reference-recording-change', renderBadges);
  window.setInterval(renderBadges, 1000);
  addPreviewControl();
  renderBadges();
})();
