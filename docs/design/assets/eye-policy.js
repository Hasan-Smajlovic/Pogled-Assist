(() => {
  'use strict';
  const choices = [
    ['both', 'Oba oka'],
    ['hold', 'Oba oka uz kratke prekide'],
    ['any', 'Jedno oko je dovoljno (probno)'],
  ];
  const validMode = value => choices.some(([mode]) => mode === value);
  const query = new URLSearchParams(location.search);
  if (validMode(query.get('policy'))) ReferenceDesign.writeSession('eye-policy', query.get('policy'));
  const requestedHold = Number(query.get('hold-ms'));
  if (query.has('hold-ms') && requestedHold >= 50 && requestedHold <= 500 && requestedHold % 50 === 0) ReferenceDesign.writeSession('eye-hold-ms', requestedHold);
  const read = () => {
    const saved = ReferenceDesign.readSession('eye-policy', 'both');
    return validMode(saved) ? saved : 'both';
  };
  function holdMs() {
    const saved = ReferenceDesign.readSession('eye-hold-ms', 150);
    return typeof saved === 'number' && Number.isFinite(saved)
      ? Math.max(50, Math.min(500, Math.round(saved / 50) * 50)) : 150;
  }
  function description() {
    if (read() === 'hold') return 'Sav napredak čuva se do ' + holdMs() + ' ms od gubitka jednog oka.' + (holdMs() < 500 ? ' Zatim se do ukupno 500 ms čuva samo završena početna pauza, bez punjenja.' : '') + ' Nastavak traži oba oka i svjež pogled na isti cilj; zastarjeli podaci poništavaju pokušaj.';
    if (read() === 'any') return 'Za početak i završetak dovoljan je pogled uz najmanje jedno praćeno oko. Probni režim: bez svježih podataka o pogledu nema odabira.';
    return 'Oba oka moraju se pratiti. Gubitak bilo kojeg oka odmah poništava nezavršen odabir.';
  }
  function setupSelect(select, changed) {
    select.replaceChildren(...choices.map(([value, label]) => new Option(label, value)));
    select.value = read();
    select.addEventListener('change', () => {
      ReferenceDesign.writeSession('eye-policy', validMode(select.value) ? select.value : 'both');
      ReferenceDesign.refreshLinks();
      changed();
    });
  }
  window.ReferenceEyePolicy = Object.freeze({
    read, holdMs, description, setupSelect,
    label: () => choices.find(([value]) => value === read())[1],
    usable: (eyes, gaze) => Boolean(gaze && (read() === 'any' ? eyes.some(value => value === true) : eyes.every(value => value === true))),
    setHoldMs: value => {
      ReferenceDesign.writeSession('eye-hold-ms', Math.max(50, Math.min(500, value)));
      ReferenceDesign.refreshLinks();
    },
  });
  ReferenceDesign.refreshLinks();
})();
