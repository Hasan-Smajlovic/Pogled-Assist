(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  function render() {
    resizeRing();
    const policy = ReferenceEyePolicy.read();
    const state = $('selection-state-preview').value;
    const pauseOnly = isPauseOnly(state, policy);
    const progress = previewProgress(state, policy, pauseOnly);
    $('selection-progress-ring').hidden = !(progress.visible && $('selection-progress-visible').checked);
    $('selection-progress-ring').dataset.state = progress.ring;
    document.querySelector('.selection-preview-target').dataset.state = progress.target;
    $('selection-progress-ring').setAttribute('aria-label', progressLabel(progress.ring, pauseOnly));
    $('selection-progress-ring').style.setProperty('--fill', pauseOnly ? '0%' : '65%');
    $('selection-mode-label').textContent = 'Režim: ' + ReferenceEyePolicy.label();
    $('selection-preview-copy').textContent = previewMessage(state, policy, progress.ring === 'held', pauseOnly);
  }
  function resizeRing() {
    const height = Number($('selection-target-height').value);
    document.querySelector('.selection-preview-buttons').style.setProperty('--target-height', `${height}px`);
    const width = $('selection-button').getBoundingClientRect().width;
    $('selection-progress-ring').style.setProperty('--ring-size', `${Math.max(0, Math.min(64, width - 16, height - 16))}px`);
  }
  function previewProgress(state, policy, pauseOnly) {
    const states = {
      active: 'active',
      fired: 'fired',
      held: { both: 'idle', hold: 'held', any: 'active' }[policy],
      resumed: policy === 'both' ? 'idle' : 'active',
      'pause-only': pauseOnly ? 'held' : 'idle',
      'pause-resumed': pauseOnly ? 'pause-resumed' : 'idle',
    };
    const displays = {
      idle: { ring: 'active', target: 'idle', visible: false },
      active: { ring: 'active', target: 'active', visible: true },
      fired: { ring: 'fired', target: 'fired', visible: true },
      held: { ring: 'held', target: 'held', visible: true },
      'pause-resumed': { ring: 'active', target: 'idle', visible: true },
    };
    return displays[states[state] || 'idle'];
  }
  function isPauseOnly(state, policy) {
    if (policy !== 'hold' || ReferenceEyePolicy.holdMs() >= 500) return false;
    return ['pause-only', 'pause-resumed'].includes(state);
  }
  function progressLabel(state, pauseOnly) {
    if (state === 'fired') return 'Odabir potvrđen';
    const label = state === 'held' ? 'Napredak na čekanju' : 'Napredak odabira';
    return label + (pauseOnly ? ': 0 posto' : ': 65 posto');
  }
  function previewMessage(state, policy, held, pauseOnly) {
    if (state === 'resumed') return resumedMessage(policy);
    const messages = {
      active: 'Svjež pogled je na dugmetu. Napredak se puni.',
      fired: 'Pun mirni krug potvrđuje odabir tokom 220 ms.',
      held: held ? 'Napredak je zamrznut. Rok: ' + ReferenceEyePolicy.holdMs() + ' ms od prvog gubitka jednog oka.' : policy === 'any' ? 'Jedno oko i svjež pogled: odabir se nastavlja.' : 'Gubitak jednog oka: napredak je poništen.',
      'pause-only': pauseOnly ? 'Čuva se završena početna pauza. Punjenje je nula; krajnji rok je ukupno 500 ms od gubitka oka.' : 'Nema dodatnog čuvanja pauze u ovom režimu ili pri trajanju 500 ms.',
      'pause-resumed': pauseOnly ? 'Oba oka i svjež pogled vraćaju završenu pauzu s nula punjenja. Slijedi cijelo novo punjenje.' : 'Nema dodatnog čuvanja pauze u ovom režimu ili pri trajanju 500 ms.',
      expired: 'Rok je istekao. Napredak je poništen i sljedeći izbor počinje ispočetka.',
      'both-lost': 'Oba oka su izgubljena. Napredak je odmah poništen u svakom režimu.',
      switch: 'Jedino praćeno oko se promijenilo. Novi izbor zahtijeva punu početnu pauzu i zadržavanje.',
      'no-gaze': 'Oko se prati, ali nema svježeg pogleda. Krug se ne puni i nema odabira.',
    };
    return messages[state];
  }
  function resumedMessage(policy) {
    if (policy === 'both') return 'Praćenje se vratilo. Ranije poništen izbor počinje ispočetka.';
    if (policy === 'any') return 'Oba oka su ponovo dostupna. Odabir se nastavlja na istom cilju.';
    return 'Prvi svjež pogled s oba oka vraća 65% napretka. Ovaj uzorak ne aktivira dugme.';
  }
  ReferenceEyePolicy.setupSelect($('selection-policy-preview'), render);
  $('selection-state-preview').addEventListener('change', render);
  $('selection-progress-visible').addEventListener('change', render);
  $('selection-target-height').addEventListener('change', render);
  window.addEventListener('resize', render);
  render();
})();
