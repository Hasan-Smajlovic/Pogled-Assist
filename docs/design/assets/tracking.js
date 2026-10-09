(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const { GROUPS } = ReferenceKeyboard;
  const trackingStates = {
    ready: { title: '', detail: '', tone: 'ready', eyes: [true, true], gaze: true },
    brief: { title: 'Praćenje je prekinuto', detail: '', tone: 'quiet', eyes: [false, true], gaze: false },
    right: { title: 'Desno oko se trenutno ne prati', detail: 'odabir je zaustavljen', tone: 'warning', eyes: [true, false], gaze: false },
    left: { title: 'Lijevo oko se trenutno ne prati', detail: 'odabir je zaustavljen', tone: 'warning', eyes: [false, true], gaze: false },
    both: { title: 'Praćenje oba oka je prekinuto', detail: 'pogledajte prema ekranu', tone: 'warning', eyes: [false, false], gaze: false },
    waiting: { title: 'Čekam podatke o pogledu', detail: 'odabir je zaustavljen', tone: 'quiet', eyes: [true, true], gaze: false },
    frequent: { title: 'Praćenje često prekida', detail: 'provjerite položaj uređaja', tone: 'warning', eyes: [true, true], gaze: true },
    disconnected: { title: 'Uređaj nije povezan', detail: 'pokušavam ponovo', tone: 'error', eyes: [null, null], gaze: false },
    stabilizing: { title: 'Praćenje se vraća', detail: '', tone: 'quiet', eyes: [true, true], gaze: true },
    recovered: { title: 'Možete nastaviti', detail: '', tone: 'ready', eyes: [true, true], gaze: true },
  };
  let trackingDemoTimers = [];
  let trackingGroup = 0;
  let trackingDemoRunning = false;
  let trackingRecoveryTimer = null;
  let trackingPreviewProgress = 0;
  let trackingNoticeOpen = false;
  $('show-tracking-feedback').checked = ReferenceDesign.readSession('feedback', true);
  const savedPreview = ReferenceDesign.readSession('tracking', null);
  if (savedPreview && ['message', 'letters', 'confirm'].includes(savedPreview.context)) {
    $('tracking-context').value = savedPreview.context;
    $('tracking-message').value = typeof savedPreview.message === 'string' ? savedPreview.message : 'TREBAM VODE';
    trackingGroup = Number.isInteger(savedPreview.group) && GROUPS[savedPreview.group] ? savedPreview.group : 0;
    [...$('tracking-letter-options').querySelectorAll('[data-tracking-letter]')].forEach((button, index) => { button.textContent = GROUPS[trackingGroup][index]; });
  }
  function stopTrackingRecovery() {
    clearTimeout(trackingRecoveryTimer);
    trackingRecoveryTimer = null;
  }
  function setTrackingState(state, progress = trackingPreviewProgress) {
    stopTrackingRecovery();
    if (state === 'ready') trackingNoticeOpen = false;
    else if (state !== 'brief') trackingNoticeOpen = true;
    $('tracking-state').value = state;
    renderTrackingPreview(progress);
    if (state === 'stabilizing') {
      trackingRecoveryTimer = setTimeout(() => setTrackingState('recovered'), 500);
    } else if (state === 'recovered') {
      trackingRecoveryTimer = setTimeout(() => setTrackingState('ready'), 2000);
    }
  }
  function stopTrackingDemo() {
    trackingDemoTimers.forEach(clearTimeout);
    trackingDemoTimers = [];
    trackingDemoRunning = false;
    $('tracking-demo').textContent = 'Prikaži prekid i povratak';
  }
  function trackingEye(label, valid) {
    const value = valid === null ? 'unknown' : String(valid);
    const symbol = valid ? '✓' : valid === null ? '?' : '—';
    return '<span class="tracking-eye" data-valid="' + value + '" aria-label="' + label + ' oko: ' + (valid ? 'prati se' : valid === null ? 'nema podataka' : 'ne prati se') + '"><svg viewBox="0 0 28 22" aria-hidden="true"><path d="M2 11s4-7 12-7 12 7 12 7-4 7-12 7S2 11 2 11Z"/><circle cx="14" cy="11" r="3.5"/></svg><b>' + label + '</b><small aria-hidden="true">' + symbol + '</small></span>';
  }
  function renderTrackingPreview(progress = trackingPreviewProgress) {
    const stateKey = $('tracking-state').value;
    const state = trackingStates[stateKey];
    const context = $('tracking-context').value;
    trackingPreviewProgress = state.gaze ? progress : 0;
    $('tracking-stage').dataset.context = context;
    const showFeedback = $('show-tracking-feedback').checked;
    $('tracking-stage').dataset.feedback = showFeedback ? 'on' : 'off';
    document.querySelector('.tracking-app').inert = context !== 'message';
    document.querySelector('.tracking-modal-layer').hidden = context === 'message';
    $('tracking-dialog-title').textContent = context === 'confirm' ? 'Obrisati cijelu poruku?' : 'Odaberite slovo';
    const background = $('tracking-background-feedback');
    const foreground = $('tracking-dialog-feedback');
    const host = context === 'message' ? background : foreground;
    (context === 'message' ? foreground : background).replaceChildren();
    if (!host.firstElementChild) {
      host.innerHTML = '<div class="tracking-feedback" aria-hidden="true" inert><div class="tracking-eyes"></div><p class="tracking-feedback-copy" role="status" aria-live="polite" aria-atomic="true"><span class="tracking-feedback-title"></span><span class="tracking-feedback-detail" hidden></span></p></div>';
    }
    const feedback = host.firstElementChild;
    const noticeVisible = showFeedback && trackingNoticeOpen;
    document.querySelector('.tracking-app .message-box').dataset.notice = String(noticeVisible && context === 'message');
    feedback.dataset.visible = String(noticeVisible);
    feedback.inert = !noticeVisible;
    feedback.setAttribute('aria-hidden', String(!noticeVisible));
    // Retain the last message while it fades out; no healthy status remains.
    if (noticeVisible) {
      feedback.dataset.tone = stateKey === 'brief' ? 'warning' : state.tone;
      const eyes = feedback.querySelector('.tracking-eyes');
      const eyeStates = state.eyes.join(',');
      if (eyes.dataset.states !== eyeStates) {
        eyes.innerHTML = trackingEye('Lijevo', state.eyes[0]) + trackingEye('Desno', state.eyes[1]);
        eyes.dataset.states = eyeStates;
      }
      const title = feedback.querySelector('.tracking-feedback-title');
      if (title.textContent !== state.title) title.textContent = state.title;
      const detail = feedback.querySelector('.tracking-feedback-detail');
      const detailText = state.detail ? ' · ' + state.detail : '';
      if (detail.textContent !== detailText) detail.textContent = detailText;
      detail.hidden = !state.detail;
    }
    document.querySelectorAll('.tracking-demo-target').forEach(button => {
      button.classList.remove('tracking-demo-target');
      button.style.removeProperty('--demo-progress');
      button.querySelector('.tracking-gaze-dot')?.remove();
    });
    if (!state.gaze || context === 'message') return;
    const target = context === 'confirm' ? $('tracking-confirm') : $('tracking-letter-options').children[2];
    target.classList.add('tracking-demo-target');
    target.style.setProperty('--demo-progress', trackingPreviewProgress + '%');
    const dot = document.createElement('span');
    dot.className = 'tracking-gaze-dot';
    dot.setAttribute('aria-hidden', 'true');
    target.append(dot);
  }
  function resizeTrackingPreview() {
    const stage = $('tracking-stage');
    if (!stage.clientWidth || !stage.clientHeight) return;
    const scale = Math.min(stage.clientWidth / 1280, stage.clientHeight / 720);
    const canvas = $('tracking-canvas');
    canvas.style.transform = 'scale(' + scale + ')';
    canvas.style.left = (stage.clientWidth - 1280 * scale) / 2 + 'px';
    canvas.style.top = (stage.clientHeight - 720 * scale) / 2 + 'px';
  }
  const trackingResizeObserver = new ResizeObserver(resizeTrackingPreview);
  trackingResizeObserver.observe($('tracking-stage'));
  function setTrackingContext(context) {
    stopTrackingDemo();
    $('tracking-context').value = context;
    renderTrackingPreview(0);
  }
  $('tracking-context').addEventListener('change', () => { stopTrackingDemo(); renderTrackingPreview(0); });
  $('tracking-state').addEventListener('change', () => { stopTrackingDemo(); setTrackingState($('tracking-state').value, 0); });
  $('show-tracking-feedback').addEventListener('change', () => {
    ReferenceDesign.writeSession('feedback', $('show-tracking-feedback').checked);
    ReferenceDesign.refreshLinks();
    renderTrackingPreview();
  });
  $('tracking-screen').addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.hasAttribute('data-tracking-context')) setTrackingContext(button.dataset.trackingContext);
    else if (button.hasAttribute('data-tracking-group')) {
      trackingGroup = Number(button.dataset.trackingGroup);
      [...$('tracking-letter-options').querySelectorAll('[data-tracking-letter]')].forEach((letterButton, index) => { letterButton.textContent = GROUPS[trackingGroup][index]; });
      setTrackingContext('letters');
    } else if (button.hasAttribute('data-tracking-letter')) {
      $('tracking-message').value += GROUPS[trackingGroup][[...button.parentElement.children].indexOf(button)];
      setTrackingContext('message');
    } else if (button.id === 'tracking-confirm') {
      $('tracking-message').value = '';
      setTrackingContext('message');
    }
  });
  $('tracking-demo').addEventListener('click', () => {
    if (trackingDemoRunning) { stopTrackingDemo(); renderTrackingPreview(); return; }
    if ($('tracking-context').value === 'message') $('tracking-context').value = 'letters';
    trackingDemoRunning = true;
    $('tracking-demo').textContent = 'Zaustavi primjer';
    const step = (delay, state, progress = 0) => {
      trackingDemoTimers.push(setTimeout(() => setTrackingState(state, progress), delay));
    };
    setTrackingState('ready', 20);
    step(650, 'ready', 55);
    step(1100, 'brief');
    step(2200, 'left');
    step(11100, 'waiting');
    step(11400, 'stabilizing', 5);
    trackingDemoTimers.push(setTimeout(() => renderTrackingPreview(35), 12600));
    trackingDemoTimers.push(setTimeout(() => renderTrackingPreview(65), 13800));
    trackingDemoTimers.push(setTimeout(() => { stopTrackingDemo(); renderTrackingPreview(0); }, 14500));
  });
  renderTrackingPreview();
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && $('tracking-context').value !== 'message' && !event.target.closest('.reference-tools, .reference-switcher')) {
      event.preventDefault(); setTrackingContext('message');
    }
  });
  window.addEventListener('pagehide', () => {
    stopTrackingDemo(); stopTrackingRecovery();
    ReferenceDesign.writeSession('tracking', { context: $('tracking-context').value, message: $('tracking-message').value, group: trackingGroup });
  });

})();
