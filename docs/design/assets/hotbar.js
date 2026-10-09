(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const gazeDemo = createReferenceGaze();
  if (ReferenceDesign.readSession('settings-save-error', false)) {
    const settingsButton = document.querySelector('[data-open-view="settings"]');
    settingsButton.textContent = 'Postavke *';
    settingsButton.title = 'Postavke nisu sačuvane. Otvorite Postavke za ponovni pokušaj.';
  }
  const hotbarStatuses = {
    ready: ['Praćenje spremno', 'Lijevo ✓   Desno ✓', '✓', '#70dfa1'],
    left: ['Praćenje pauzirano', 'Lijevo —   Desno ✓', 'Ⅱ', '#f2ce76'],
    right: ['Praćenje pauzirano', 'Lijevo ✓   Desno —', 'Ⅱ', '#f2ce76'],
    eyes: ['Praćenje pauzirano', 'Lijevo —   Desno —', 'Ⅱ', '#f2ce76'],
    waiting: ['Čekam podatke', 'Čekam svježe podatke', '◷', '#f2ce76'],
    connecting: ['Povezivanje…', 'Tražim Tobii uređaj', '◷', '#f2ce76'],
    retrying: ['Uređaj nije povezan', 'Pokušavam ponovo', '!', '#ffa0a8'],
    simulation: ['Simulacija mišem', 'Upravljanje mišem', '↖', '#a0cef3'],
    unavailable: ['Simulacija nedostupna', 'Glavni ekran nije dostupan', '!', '#ffa0a8'],
    stopped: ['Praćenje zaustavljeno', 'Praćenje nije pokrenuto', 'Ⅱ', '#bec9d9'],
  };
  $('hotbar-status-preview').addEventListener('change', event => {
    const [title, detail, icon, color] = hotbarStatuses[event.target.value];
    $('hotbar-tracking-title').textContent = title;
    $('hotbar-tracking-detail').textContent = detail;
    $('hotbar-tracking-icon').textContent = icon;
    $('hotbar-tracking-status').style.setProperty('--tracking-color', color);
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

})();
