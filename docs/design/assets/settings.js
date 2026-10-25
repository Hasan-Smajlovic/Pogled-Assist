(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let learnedWords = ['ĆEVAPI', 'DŽEZ', 'KAHVA', 'LJETO', 'NJIVA', 'ŠETNJA'];
  let selectedWord = null;
  let arabic = ReferenceKeyboard.readScript();
  let startupTimer;
  let voiceTestTimer;
  const query = new URLSearchParams(location.search);
  const settingsPages = ['general-settings', 'support-settings', 'gaze-settings', 'speech-settings', 'eleven-settings', 'audio-settings', 'learning-settings'];
  const voiceNames = { standard: 'Standardni', natural: 'Prirodni', efendija: 'Efendija' };
  let selectedVoice = query.get('voice') || ReferenceDesign.readSession('voice', 'standard');
  if (!Object.hasOwn(voiceNames, selectedVoice)) selectedVoice = 'standard';
  const requestedConnection = query.get('connection');
  if (['connected', 'empty', 'missing', 'unverified', 'permission', 'save-failed', 'quota', 'invalid', 'offline'].includes(requestedConnection)) $('eleven-demo-state').value = requestedConnection;
  let hasSavedKey = $('eleven-demo-state').value !== 'missing';
  let editingKey = query.get('edit-key') === 'true' || $('eleven-demo-state').value === 'save-failed';
  function clearKeyInput() {
    $('eleven-api-key').value = '';
    $('eleven-api-key').type = 'password';
    $('show-eleven-key').textContent = 'Prikaži';
    $('show-eleven-key').setAttribute('aria-pressed', 'false');
  }
  $('replace-eleven-key').addEventListener('click', () => {
    clearKeyInput();
    editingKey = true;
    renderConnection();
    $('eleven-api-key').focus({ preventScroll: true });
  });
  $('cancel-eleven-key').addEventListener('click', () => {
    clearKeyInput();
    editingKey = false;
    renderConnection();
  });
  $('release-version').addEventListener('change', () => {
    document.querySelector('[data-settings-action="install-update"]').disabled = $('release-version').value === 'v0.3.5';
  });
  function previewStartupChange() {
    clearTimeout(startupTimer);
    $('settings-status').textContent = $('startup-enabled').checked
      ? 'Uključujem pokretanje uz Windows.' : 'Isključujem pokretanje uz Windows.';
    startupTimer = setTimeout(() => {
      $('settings-status').textContent = $('startup-enabled').checked
        ? 'Pokretanje uz Windows je uključeno.' : 'Pokretanje uz Windows je isključeno.';
    }, 800);
  }
  $('startup-enabled').addEventListener('change', previewStartupChange);
  $('logging-enabled').checked = ReferenceDesign.readSession('logging-enabled', false);
  $('logging-enabled').addEventListener('change', event => {
    ReferenceDesign.writeSession('logging-enabled', event.target.checked);
    $('settings-status').textContent = event.target.checked ? 'Opće zapisivanje je uključeno.' : 'Opće zapisivanje je isključeno. Ručno pokrenuto dijagnostičko snimanje nastavlja do svog završetka.';
  });
  $('startup-launcher').addEventListener('change', () => {
    if ($('startup-enabled').checked) previewStartupChange();
    else $('settings-status').textContent = $('startup-launcher').checked
      ? 'PowerShell prozor će biti prikazan pri pokretanju.'
      : 'PowerShell pokretač će raditi tiho u pozadini.';
  });
  function renderScript() {
    $('settings-script-preview').textContent = arabic ? 'Arapski' : 'Latinica';
    $('voice-hint').textContent = arabic ? 'Izbor bosanskog glasa ostaje sačuvan za povratak na latinicu.' : 'Standardni radi bez interneta. Prirodni i Efendija trebaju internet.';
    $('voice-choices').hidden = arabic;
    $('arabic-voice-preview').hidden = !arabic;
    $('eleven-summary').hidden = arabic || selectedVoice !== 'efendija';
    $('standard-speed').hidden = arabic || selectedVoice !== 'standard';
    for (const option of document.querySelectorAll('[data-voice]')) option.checked = option.dataset.voice === selectedVoice;
    $('test-selected-voice').textContent = !arabic && selectedVoice === 'efendija' ? 'Isprobaj Efendiju' : 'Isprobaj govor';
  }
  $('settings-script-preview').addEventListener('click', () => {
    arabic = !arabic;
    ReferenceKeyboard.writeScript(arabic);
    renderScript();
  });
  $('show-tracking-feedback').checked = ReferenceDesign.readSession('feedback', true);
  function renderEyePolicy() {
    const holding = ReferenceEyePolicy.read() === 'hold';
    const duration = ReferenceEyePolicy.holdMs();
    $('eye-policy-hint').textContent = ReferenceEyePolicy.description();
    $('eye-hold-value').textContent = duration + ' ms';
    $('eye-hold-row').dataset.disabled = String(!holding);
    $('eye-hold-hint').textContent = holding ? 'Čuvanje napretka pri gubitku jednog oka: 50 do 500 ms.' : 'Dostupno samo u režimu „Oba oka uz kratke prekide“. Sačuvano trajanje ostaje isto.';
    $('eye-hold-less').disabled = !holding || duration <= 50;
    $('eye-hold-more').disabled = !holding || duration >= 500;
  }
  ReferenceEyePolicy.setupSelect($('eye-policy'), () => {
    renderEyePolicy();
    $('settings-status').textContent = 'Režim je promijenjen. Odabir počinje ispočetka.';
  });
  for (const [id, delta] of [['eye-hold-less', -50], ['eye-hold-more', 50]]) {
    $(id).addEventListener('click', () => {
      ReferenceEyePolicy.setHoldMs(ReferenceEyePolicy.holdMs() + delta);
      renderEyePolicy();
      $('settings-status').textContent = 'Čuvanje napretka: ' + ReferenceEyePolicy.holdMs() + ' ms.';
    });
  }
  const storedEdgeHold = Number(ReferenceDesign.readSession('edge-hold-ms', 120));
  let edgeHoldMs = Number.isFinite(storedEdgeHold) ? Math.min(300, Math.max(0, Math.round(storedEdgeHold / 20) * 20)) : 120;
  function renderEdgeHold() {
    $('edge-hold-value').textContent = edgeHoldMs === 0 ? 'Isključeno' : edgeHoldMs + ' ms';
  }
  for (const [id, delta] of [['edge-hold-less', -20], ['edge-hold-more', 20]]) {
    $(id).addEventListener('click', () => {
      edgeHoldMs = Math.min(300, Math.max(0, edgeHoldMs + delta));
      ReferenceDesign.writeSession('edge-hold-ms', edgeHoldMs);
      renderEdgeHold();
      $('settings-status').textContent = 'Čuvanje odabira uz rub je ažurirano. Odabir počinje ispočetka.';
    });
  }
  renderEdgeHold();
  function showGazeTab(name) {
    for (const button of document.querySelectorAll('[data-gaze-tab]')) {
      const selected = button.dataset.gazeTab === name;
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
      $(button.getAttribute('aria-controls')).hidden = !selected;
    }
  }
  for (const button of document.querySelectorAll('[data-gaze-tab]')) {
    button.addEventListener('click', () => showGazeTab(button.dataset.gazeTab));
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const tabs = [...document.querySelectorAll('[data-gaze-tab]')];
      const index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
        : (tabs.indexOf(button) + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      showGazeTab(tabs[index].dataset.gazeTab);
      tabs[index].focus();
    });
  }
  showGazeTab(['pointer', 'stability'].includes(query.get('gaze-tab')) ? query.get('gaze-tab') : 'selection');
  renderEyePolicy();
  for (const button of document.querySelectorAll('[data-voice]')) button.addEventListener('click', () => {
    selectedVoice = button.dataset.voice;
    ReferenceDesign.writeSession('voice', selectedVoice);
    $('selected-voice-test-status').textContent = '';
    renderScript();
  });
  $('show-eleven-key').addEventListener('click', () => {
    const visible = $('eleven-api-key').type === 'password';
    $('eleven-api-key').type = visible ? 'text' : 'password';
    $('show-eleven-key').textContent = visible ? 'Sakrij' : 'Prikaži';
    $('show-eleven-key').setAttribute('aria-pressed', String(visible));
  });
  $('save-eleven-key').addEventListener('click', () => {
    if (!$('eleven-api-key').value.trim()) {
      $('eleven-connection-status').textContent = 'Unesite API ključ prije čuvanja.';
      $('eleven-connection-status').dataset.tone = 'error';
      return;
    }
    if ($('eleven-demo-state').value === 'save-failed') {
      $('eleven-api-key').type = 'password';
      $('show-eleven-key').textContent = 'Prikaži';
      $('show-eleven-key').setAttribute('aria-pressed', 'false');
      $('eleven-connection-status').textContent = 'Ključ nije sačuvan. Pokušajte ponovo.';
      $('eleven-connection-status').dataset.tone = 'error';
      return;
    }
    hasSavedKey = true;
    editingKey = false;
    $('eleven-api-key').value = '';
    $('eleven-api-key').type = 'password';
    $('show-eleven-key').textContent = 'Prikaži';
    $('show-eleven-key').setAttribute('aria-pressed', 'false');
    $('eleven-demo-state').value = 'unverified';
    renderConnection();
  });
  $('check-eleven-connection').addEventListener('click', () => {
    if (editingKey || $('eleven-api-key').value) {
      $('eleven-connection-status').textContent = 'Sačuvajte novi ključ ili odaberite Odustani prije provjere veze.';
      $('eleven-connection-status').dataset.tone = 'error';
      return;
    }
    if (!hasSavedKey) $('eleven-demo-state').value = 'missing';
    else if ($('eleven-demo-state').value === 'unverified') $('eleven-demo-state').value = 'connected';
    renderConnection();
  });
  $('remove-eleven-key').addEventListener('click', () => {
    $('eleven-api-key').value = '';
    hasSavedKey = false;
    editingKey = false;
    $('eleven-demo-state').value = 'missing';
    $('eleven-test-status').textContent = '';
    renderConnection();
  });
  $('eleven-demo-state').addEventListener('change', () => {
    hasSavedKey = $('eleven-demo-state').value !== 'missing';
    editingKey = $('eleven-demo-state').value === 'save-failed';
    $('eleven-api-key').value = '';
    clearTimeout(voiceTestTimer);
    $('eleven-test-status').textContent = '';
    $('selected-voice-test-status').textContent = '';
    renderConnection();
  });
  $('eleven-model').addEventListener('change', () => {
    renderConnection();
    $('eleven-test-status').textContent = 'Model je promijenjen. Isprobajte glas s novim modelom.';
    $('eleven-test-status').dataset.tone = '';
  });
  $('test-eleven-voice').addEventListener('click', () => previewVoiceTest('eleven-test-status', 'efendija'));
  for (const id of ['similarity']) $(id).addEventListener('input', () => { $(`${id}-value`).textContent = `${$(id).value}%`; });
  document.querySelectorAll('[data-tune]').forEach(button => button.addEventListener('click', () => {
    const slider = $(button.dataset.tune);
    slider.value = Math.max(0, Math.min(100, Number(slider.value) + Number(button.dataset.step)));
    slider.dispatchEvent(new Event('input'));
  }));
  document.querySelectorAll('[data-stability]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-stability]').forEach(choice => choice.setAttribute('aria-pressed', String(choice === button)));
  }));
  $('stop-test-voice').addEventListener('click', () => stopVoiceTest('eleven-test-status'));
  $('stop-selected-voice').addEventListener('click', () => stopVoiceTest('selected-voice-test-status'));

  function stopVoiceTest(targetId) {
    clearTimeout(voiceTestTimer);
    $(targetId).textContent = 'Govor je zaustavljen.';
    renderTestPlayback(false);
  }

  function renderTestPlayback(active) {
    for (const [test, stop, progress] of [
      ['test-selected-voice', 'stop-selected-voice', 'selected-voice-progress'],
      ['test-eleven-voice', 'stop-test-voice', 'test-voice-progress'],
    ]) {
      $(test).disabled = active;
      $(stop).hidden = false;
      $(stop).disabled = !active;
      $(progress).hidden = !active;
      if (active) $(test).textContent = 'Pripremam…';
    }
    if (!active) {
      $('test-eleven-voice').textContent = 'Isprobaj Efendiju';
      renderScript();
      renderConnection();
    }
  }
  $('test-selected-voice').addEventListener('click', () => previewVoiceTest('selected-voice-test-status', arabic ? 'hamed' : selectedVoice));
  $('clear-saved-audio').addEventListener('click', () => {
    $('saved-audio-status').textContent = 'Sačuvani zvuk je obrisan. Fraze i odgovori ostaju sačuvani.';
  });
  $('settings-save-error').checked = ReferenceDesign.readSession('settings-save-error', false);
  function renderFeedbackLink() {
    $('tracking-setting-preview').href = ReferenceDesign.pageUrl('tracking', { feedback: $('show-tracking-feedback').checked ? 'on' : 'off' });
  }
  $('show-tracking-feedback').addEventListener('change', () => {
    ReferenceDesign.writeSession('feedback', $('show-tracking-feedback').checked);
    ReferenceDesign.refreshLinks();
    renderFeedbackLink();
  });
  for (const button of document.querySelectorAll('[data-settings-action]')) button.addEventListener('click', () => handleSettingsAction(button.dataset.settingsAction));
  $('settings-save-error').addEventListener('change', renderStorageState);
  $('learning-demo-state').addEventListener('change', renderLearning);
  renderScript(); renderConnection(); renderFeedbackLink(); renderStorageState(); renderLearning();
  const initialTab = query.get('page') || location.hash.slice(1);
  if (settingsPages.includes(initialTab)) handleSettingsAction(initialTab);
  window.addEventListener('hashchange', () => {
    const tab = location.hash.slice(1);
    if (settingsPages.includes(tab)) showSettingsTab(tab);
  });
  function handleSettingsAction(action) {
    if (action === 'retry-settings') {
      $('settings-save-error').checked = false; renderStorageState();
      $('settings-status').textContent = 'Postavke su sačuvane.'; return;
    }
    if (settingsPages.includes(action)) {
      showSettingsTab(action);
      return;
    }
    if (action === 'forget-word' && selectedWord) {
      forgetSelectedWord();
      return;
    }
    if (action === 'retry-learning') {
      $('learning-demo-state').value = 'saved'; renderLearning(); return;
    }
    const status = $('update-status');
    const pageStatus = $('settings-status');
    const checkButton = document.querySelector('[data-settings-action="check-update"]');
    const installButton = document.querySelector('[data-settings-action="install-update"]');
    if (action === 'check-update') {
      status.textContent = 'Dostupna je novija verzija v0.4.0.';
      pageStatus.textContent = 'Lista verzija je osvježena.';
      installButton.hidden = false;
    } else if (action === 'install-update') {
      checkButton.disabled = true;
      installButton.disabled = true;
      $('release-version').disabled = true;
      status.textContent = `Paket ${$('release-version').value} je provjeren. Potvrdite ponovno pokretanje.`;
      $('version-warning').hidden = false;
      pageStatus.textContent = 'Nesačuvan unos.';
    } else if (action === 'cancel-install') {
      $('version-warning').hidden = true;
      checkButton.disabled = false; installButton.disabled = false;
      $('release-version').disabled = false;
      status.textContent = 'Instalacija je otkazana. Trenutna verzija i unos ostaju dostupni.';
    } else if (action === 'confirm-install') {
      $('version-warning').hidden = true;
      status.textContent = 'Instaliram odabranu verziju i ponovo pokrećem aplikaciju.';
    }
  }

  function showSettingsTab(action) {
    if (action !== 'eleven-settings') {
      clearKeyInput();
      editingKey = false;
      renderConnection();
    }
    for (const id of settingsPages) $(id).hidden = id !== action;
    const navAction = ['eleven-settings', 'audio-settings', 'learning-settings'].includes(action) ? 'speech-settings' : action;
    for (const button of document.querySelectorAll('.settings-nav [data-settings-action]')) {
      if (button.dataset.settingsAction === navAction) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    }
    const url = new URL(location.href);
    url.hash = '';
    url.searchParams.set('page', action);
    history.replaceState(null, '', url);
    renderStorageState();
    if (action === 'learning-settings') renderLearning();
    $(action).scrollTop = 0;
  }

  function renderConnection() {
    const state = $('eleven-demo-state').value;
    const states = {
      connected: ['ElevenLabs je povezan', 'ElevenLabs je povezan. Provjera veze ne troši kredite.'],
      empty: ['ElevenLabs je povezan', 'ElevenLabs je povezan. Provjera veze ne troši kredite.'],
      missing: ['ElevenLabs nije povezan', 'Dodajte ElevenLabs ključ.'],
      unverified: ['Provjerite vezu s ElevenLabsom', 'Ključ je sačuvan. Provjerite vezu.'],
      permission: ['Nedostaju dozvole ključa', 'Za listu glasova dozvolite čitanje glasova na ElevenLabs ključu.'],
      'save-failed': ['Ključ nije sačuvan', 'Ključ nije sačuvan. Pokušajte ponovo.'],
      quota: ['Nema dovoljno ElevenLabs kredita', 'ElevenLabs je povezan. Provjera veze ne troši kredite.'],
      invalid: ['Provjerite API ključ', 'Provjerite ElevenLabs ključ u Postavkama.'],
      offline: ['ElevenLabs trenutno nije dostupan', 'ElevenLabs trenutno nije dostupan.'],
    };
    const [, status] = states[state];
    $('eleven-summary').dataset.tone = state === 'connected' ? '' : 'warning';
    $('eleven-summary-title').textContent = 'Efendija · ElevenLabs';
    $('eleven-summary-copy').textContent = status;
    $('eleven-connection-status').textContent = status;
    $('eleven-api-key').placeholder = hasSavedKey ? 'Unesite novi API ključ' : 'Unesite API ključ';
    $('saved-eleven-key').hidden = !hasSavedKey || editingKey;
    $('edit-eleven-key').hidden = hasSavedKey && !editingKey;
    $('cancel-eleven-key').hidden = !hasSavedKey;
    $('eleven-connection-status').dataset.tone = ['missing', 'invalid', 'permission', 'save-failed', 'offline'].includes(state) ? 'error' : '';
    renderCatalogs(state);
    renderCredits(state);
  }

  function renderCatalogs(state) {
    for (const id of ['eleven-voice', 'eleven-model', 'test-eleven-voice']) $(id).disabled = ['missing', 'unverified', 'invalid', 'permission', 'save-failed'].includes(state);
    const needsVoiceCheck = ['missing', 'unverified', 'invalid', 'permission', 'save-failed'].includes(state);
    const voiceLabel = needsVoiceCheck ? 'Provjerite vezu' : state === 'empty' ? 'Nema glasova' : 'Efendija Fikret';
    $('eleven-voice').replaceChildren(new Option(voiceLabel, needsVoiceCheck || state === 'empty' ? '' : 'preview-voice'));
    if (state === 'empty') {
      $('eleven-voice').disabled = true;
      $('test-eleven-voice').disabled = true;
    }
    $('remove-eleven-key').disabled = !hasSavedKey;
    $('check-eleven-connection').disabled = !hasSavedKey;
  }

  function renderCredits(state) {
    const credit = state === 'quota' ? 0 : state === 'connected' ? 80 : null;
    $('credit-label').textContent = credit === null ? 'Stanje kredita nije dostupno.' : `Preostalo ${credit === 0 ? '0' : '24.000'} / 30.000 kredita (${credit}%)`;
    $('credit-progress').hidden = credit === null;
    $('credit-progress').value = credit || 0;
    $('credit-progress').parentElement.dataset.tone = credit === 0 ? 'error' : '';
    $('credit-note').textContent = credit === null ? 'Potrebni su veza s ElevenLabsom i dozvola za čitanje podataka o računu.' : 'Posljednje provjereno stanje računa. Osvježava se pri otvaranju i nakon govora.';
  }

  function unsavedTestKey(voice) {
    if (voice !== 'efendija') return false;
    return Boolean(editingKey || $('eleven-api-key').value);
  }

  function previewVoiceTest(targetId, voice) {
    if (unsavedTestKey(voice)) {
      $('eleven-connection-status').textContent = 'Sačuvajte novi ključ ili odaberite Odustani prije probe glasa.';
      $('eleven-connection-status').dataset.tone = 'error';
      return;
    }
    clearTimeout(voiceTestTimer);
    const target = $(targetId);
    const name = voiceNames[voice] || 'Hamed';
    target.dataset.tone = '';
    target.textContent = `Pripremam probu: ${name}…`;
    renderTestPlayback(true);
    voiceTestTimer = setTimeout(() => finishVoiceTest(target, name, voice), 650);
  }

  function finishVoiceTest(target, name, voice) {
      const state = $('eleven-demo-state').value;
      const errors = { empty: 'dodajte glas u svoju kolekciju.', quota: 'nema dovoljno ElevenLabs kredita.', invalid: 'API ključ nije prihvaćen.', permission: 'ključ nema potrebne dozvole.', 'save-failed': 'ključ nije sačuvan.', offline: 'servis trenutno nije dostupan.', missing: 'prvo unesite API ključ.', unverified: 'prvo provjerite vezu.' };
      if (voice === 'efendija' && state !== 'connected') {
        target.dataset.tone = 'error';
        target.textContent = 'Proba Efendije nije uspjela: ' + errors[state];
      } else target.textContent = `Proba glasa ${name} je završena.`;
      renderTestPlayback(false);
  }

  function forgetSelectedWord() {
    if ($('learning-demo-state').value === 'write') {
      $('learning-status').textContent = 'Učenje nije sačuvano. Pokušajte ponovo.';
      $('retry-learning').disabled = false;
    } else {
      learnedWords = learnedWords.filter(word => word !== selectedWord);
      selectedWord = null; renderLearning();
      $('learning-status').textContent = 'Riječ je zaboravljena. Vaša poruka je sačuvana.';
    }
  }

  function renderLearning() {
    const state = $('learning-demo-state').value;
    const available = state === 'read' || state === 'empty' ? [] : learnedWords;
    $('learned-words').replaceChildren();
    available.forEach(word => {
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = word;
      button.setAttribute('aria-pressed', String(selectedWord === word));
      button.onclick = () => { selectedWord = word; renderLearning(); };
      $('learned-words').append(button);
    });
    $('learning-selection').textContent = selectedWord ? `Odabrano: ${selectedWord}` : available.length ? 'Odaberite riječ.' : state === 'read' ? 'Naučene riječi nisu učitane.' : 'Nema naučenih riječi.';
    $('forget-word').disabled = !available.includes(selectedWord);
    $('learning-status').textContent = state === 'read' ? 'Datoteka nije učitana i nije promijenjena. Pokušajte ponovo.' : state === 'write' ? 'Učenje nije sačuvano. Pokušajte ponovo.' : 'Učenje je sačuvano.';
    $('retry-learning').disabled = !['read', 'write'].includes(state);
  }

  function renderStorageState() {
    const failed = $('settings-save-error').checked;
    ReferenceDesign.writeSession('settings-save-error', failed);
    $('settings-save-note').textContent = failed ? 'Postavke nisu sačuvane. Važe do zatvaranja aplikacije.' : !$('eleven-settings').hidden ? 'Glas i model se čuvaju automatski. Ključ potvrdite dugmetom Sačuvaj ključ.' : 'Promjene se primjenjuju i čuvaju automatski.';
    $('settings-save-state').dataset.tone = failed ? 'error' : '';
    $('retry-settings').hidden = !failed;
  }


})();
