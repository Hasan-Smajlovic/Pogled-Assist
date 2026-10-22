(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const gazeDemo = createReferenceGaze();
  if (ReferenceDesign.readSession('settings-save-error', false)) {
    const settingsButton = document.querySelector('[data-open-view="settings"]');
    settingsButton.querySelector('[data-settings-label]').textContent = 'Postavke *';
    settingsButton.title = 'Postavke nisu sačuvane. Otvorite Postavke za ponovni pokušaj.';
  }
  const hotbarStatuses = {
    ready: ['Praćenje spremno', 'Lijevo ✓   Desno ✓', '✓', '#70dfa1'],
    left: ['Praćenje pauzirano', 'Lijevo —   Desno ✓', 'Ⅱ', '#f2ce76'],
    right: ['Praćenje pauzirano', 'Lijevo ✓   Desno —', 'Ⅱ', '#f2ce76'],
    eyes: ['Praćenje pauzirano', 'Lijevo —   Desno —', 'Ⅱ', '#f2ce76'],
    waiting: ['Čekam podatke', 'Čekam svježe podatke', '◷', '#f2ce76'],
    hold: ['Praćenje pauzirano', 'Lijevo —   Desno ✓', 'Ⅱ', '#f2ce76'],
    'one-waiting': ['Čekam podatke', 'Nema svježeg pogleda', '◷', '#f2ce76'],
    connecting: ['Povezivanje…', 'Tražim Tobii uređaj', '◷', '#f2ce76'],
    retrying: ['Uređaj nije povezan', 'Pokušavam ponovo', '!', '#ffa0a8'],
    simulation: ['Simulacija mišem', 'Upravljanje mišem', '↖', '#a0cef3'],
    'simulation-left': ['Simulacija mišem', 'Lijevo —   Desno ✓', '↖', '#a0cef3'],
    'simulation-paused': ['Simulacija mišem', 'Isporuka pogleda pauzirana', '↖', '#a0cef3'],
    'simulation-disconnected': ['Simulacija mišem', 'Veza je prekinuta', '↖', '#a0cef3'],
    unavailable: ['Simulacija nedostupna', 'Glavni ekran nije dostupan', '!', '#ffa0a8'],
    stopped: ['Praćenje zaustavljeno', 'Praćenje nije pokrenuto', 'Ⅱ', '#bec9d9'],
  };
  function renderStatus() {
    const state = $('hotbar-status-preview').value;
    let [title, detail, icon, color] = hotbarStatuses[state];
    if (['left', 'right', 'hold'].includes(state) && ReferenceEyePolicy.read() === 'any') {
      title = 'Odabir jednim okom'; icon = '✓'; color = '#70dfa1';
    } else if (state === 'hold' && ReferenceEyePolicy.read() === 'hold') {
      title = 'Odabir na čekanju';
    }
    $('hotbar-tracking-title').textContent = title;
    $('hotbar-tracking-detail').textContent = detail;
    $('hotbar-tracking-icon').textContent = icon;
    $('hotbar-tracking-status').style.setProperty('--tracking-color', color);
  }
  $('hotbar-status-preview').addEventListener('change', renderStatus);
  ReferenceEyePolicy.setupSelect($('hotbar-policy-preview'), () => {
    renderStatus(); renderMarker(); gazeDemo.reset();
  });
  $('hotbar-hide').addEventListener('click', () => {
    document.querySelector('.hotbar-reference').hidden = true;
    $('hotbar-restore').hidden = false;
    gazeDemo.reset();
  });
  $('hotbar-restore').addEventListener('click', () => {
    document.querySelector('.hotbar-reference').hidden = false;
    $('hotbar-restore').hidden = true;
    gazeDemo.reset();
  });

  function renderMarker() {
    const state = $('marker-state-preview').value;
    const visible = state === 'fresh' || state === 'resumed' || state === 'eye-loss' && ReferenceEyePolicy.read() === 'any';
    $('marker-preview-dot').hidden = !visible;
    $('marker-preview-dot').style.left = state === 'resumed' ? '40%' : '60%';
    $('marker-preview-status').textContent = visible ? 'Svježa pozicija pogleda' : 'Oznaka je skrivena do novog validnog pogleda';
  }
  $('marker-state-preview').addEventListener('change', renderMarker);
  renderStatus(); renderMarker();
})();
