(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  function render() {
    const height = Number($('selection-target-height').value);
    document.querySelector('.selection-preview-buttons').style.setProperty('--target-height', `${height}px`);
    const width = $('selection-button').getBoundingClientRect().width;
    $('selection-progress-ring').style.setProperty('--ring-size', `${Math.max(0, Math.min(64, width - 16, height - 16))}px`);
    const policy = ReferenceEyePolicy.read();
    const state = $('selection-state-preview').value;
    const active = state === 'active' || state === 'resumed' && policy !== 'both' || state === 'held' && policy === 'any';
    const held = state === 'held' && policy === 'hold';
    const fired = state === 'fired';
    const visible = (active || held || fired) && $('selection-progress-visible').checked;
    $('selection-progress-ring').hidden = !visible;
    $('selection-progress-ring').dataset.state = held ? 'held' : fired ? 'fired' : 'active';
    document.querySelector('.selection-preview-target').dataset.state = held ? 'held' : fired ? 'fired' : active ? 'active' : 'idle';
    $('selection-progress-ring').setAttribute('aria-label', fired ? 'Odabir potvrđen' : (held ? 'Napredak na čekanju' : 'Napredak odabira') + ': 65 posto');
    $('selection-mode-label').textContent = 'Režim: ' + ReferenceEyePolicy.label();
    const messages = {
      active: 'Svjež pogled je na dugmetu. Napredak se puni.',
      fired: 'Pun mirni krug potvrđuje odabir tokom 220 ms.',
      held: held ? 'Napredak je zamrznut. Rok: ' + ReferenceEyePolicy.holdMs() + ' ms od prvog gubitka jednog oka.' : policy === 'any' ? 'Jedno oko i svjež pogled: odabir se nastavlja.' : 'Gubitak jednog oka: napredak je poništen.',
      resumed: 'Prvi svjež pogled s oba oka vraća 65% napretka. Ovaj uzorak ne aktivira dugme.',
      expired: 'Rok je istekao. Napredak je poništen i sljedeći izbor počinje ispočetka.',
      'both-lost': 'Oba oka su izgubljena. Napredak je odmah poništen u svakom režimu.',
      switch: 'Jedino praćeno oko se promijenilo. Novi izbor zahtijeva punu početnu pauzu i zadržavanje.',
      'no-gaze': 'Oko se prati, ali nema svježeg pogleda. Krug se ne puni i nema odabira.',
    };
    $('selection-preview-copy').textContent = state === 'resumed' && policy === 'both'
      ? 'Praćenje se vratilo. Ranije poništen izbor počinje ispočetka.'
      : state === 'resumed' && policy === 'any' ? 'Oba oka su ponovo dostupna. Odabir se nastavlja na istom cilju.' : messages[state];
  }
  ReferenceEyePolicy.setupSelect($('selection-policy-preview'), render);
  $('selection-state-preview').addEventListener('change', render);
  $('selection-progress-visible').addEventListener('change', render);
  $('selection-target-height').addEventListener('change', render);
  window.addEventListener('resize', render);
  render();
})();
