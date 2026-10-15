(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let learnedWords = ['ĆEVAPI', 'DŽEZ', 'KAHVA', 'LJETO', 'NJIVA', 'ŠETNJA'];
  let selectedWord = null;
  let arabic = ReferenceKeyboard.readScript();
  let startupTimer;
  let voiceTestTimer;
  const query = new URLSearchParams(location.search);
  const settingsPages = ['general-settings', 'gaze-settings', 'speech-settings', 'eleven-settings', 'audio-settings', 'learning-settings'];
  const voiceNames = { standard: 'Standardni', natural: 'Prirodni', efendija: 'Efendija' };
  let selectedVoice = query.get('voice') || ReferenceDesign.readSession('voice', 'standard');
  if (!Object.hasOwn(voiceNames, selectedVoice)) selectedVoice = 'standard';
  const requestedConnection = query.get('connection');
  if (['connected', 'missing', 'unverified', 'quota', 'invalid', 'offline'].includes(requestedConnection)) $('eleven-demo-state').value = requestedConnection;
  if ($('eleven-demo-state').value !== 'missing') $('eleven-api-key').value = 'probni-kljuc-za-nacrt';
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
  $('startup-launcher').addEventListener('change', () => {
    if ($('startup-enabled').checked) previewStartupChange();
    else $('settings-status').textContent = $('startup-launcher').checked
      ? 'PowerShell prozor će biti prikazan pri pokretanju.'
      : 'PowerShell pokretač će raditi tiho u pozadini.';
  });
  function renderScript() {
    $('settings-script-preview').textContent = arabic ? 'Arapski' : 'Latinica';
    $('voice-hint').textContent = arabic ? 'Arapski koristi Hamed uz internet. Izbor bosanskog glasa ostaje sačuvan.' : 'Izbor glasa ostaje sačuvan i kada se koristi zamjenski.';
    $('voice-choices').hidden = arabic;
    $('arabic-voice-preview').hidden = !arabic;
    $('eleven-summary').hidden = arabic || selectedVoice !== 'efendija';
    $('standard-speed').hidden = arabic || selectedVoice !== 'standard';
    for (const button of document.querySelectorAll('[data-voice]')) button.setAttribute('aria-pressed', String(button.dataset.voice === selectedVoice));
    $('test-selected-voice').textContent = '▶  Isprobaj ' + (arabic ? 'Hameda' : { standard: 'Standardni glas', natural: 'Prirodni glas', efendija: 'Efendiju' }[selectedVoice]);
  }
  $('settings-script-preview').addEventListener('click', () => {
    arabic = !arabic;
    ReferenceKeyboard.writeScript(arabic);
    renderScript();
  });
  $('show-tracking-feedback').checked = ReferenceDesign.readSession('feedback', true);
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
    $('eleven-api-key').value = 'probni-kljuc-za-nacrt';
    $('eleven-api-key').type = 'password';
    $('show-eleven-key').textContent = 'Prikaži';
    $('show-eleven-key').setAttribute('aria-pressed', 'false');
    $('eleven-demo-state').value = 'unverified';
    renderConnection();
  });
  $('check-eleven-connection').addEventListener('click', () => {
    if (!$('eleven-api-key').value.trim()) $('eleven-demo-state').value = 'missing';
    else if ($('eleven-demo-state').value === 'unverified') $('eleven-demo-state').value = 'connected';
    renderConnection();
  });
  $('remove-eleven-key').addEventListener('click', () => {
    $('eleven-api-key').value = '';
    $('eleven-demo-state').value = 'missing';
    $('eleven-test-status').textContent = '';
    renderConnection();
  });
  $('eleven-demo-state').addEventListener('change', () => {
    $('eleven-api-key').value = $('eleven-demo-state').value === 'missing' ? '' : 'probni-kljuc-za-nacrt';
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
    for (const id of settingsPages) $(id).hidden = id !== action;
    const navAction = ['eleven-settings', 'audio-settings', 'learning-settings'].includes(action) ? 'speech-settings' : action;
    for (const button of document.querySelectorAll('.settings-nav [data-settings-action]')) button.setAttribute('aria-pressed', String(button.dataset.settingsAction === navAction));
    const url = new URL(location.href);
    url.hash = '';
    url.searchParams.set('page', action);
    history.replaceState(null, '', url);
    renderStorageState();
    if (action === 'learning-settings') renderLearning();
  }

  function renderConnection() {
    const state = $('eleven-demo-state').value;
    const states = {
      connected: ['ElevenLabs je povezan', 'Ključ je prihvaćen. Glas i model su dostupni.'],
      missing: ['ElevenLabs nije povezan', 'Unesite i sačuvajte API ključ, zatim provjerite vezu.'],
      unverified: ['Provjerite vezu s ElevenLabsom', 'Ključ je sačuvan. Odaberite Provjeri vezu.'],
      quota: ['Nema dovoljno ElevenLabs kredita', 'Ključ je prihvaćen. Za posljednji izgovor nije bilo dovoljno kredita.'],
      invalid: ['Provjerite API ključ', 'Ključ nije prihvaćen. Provjerite unos i dozvole ključa.'],
      offline: ['ElevenLabs trenutno nije dostupan', 'Vezu nije moguće provjeriti. Pokušajte kada internet bude dostupan.'],
    };
    const [title, status] = states[state];
    $('eleven-summary').dataset.tone = state === 'connected' ? '' : 'warning';
    $('eleven-summary-title').textContent = title;
    const model = $('eleven-model').selectedOptions[0].textContent;
    $('eleven-summary-copy').textContent = state === 'missing' ? 'Unesite ključ i odaberite glas.' : `Efendija FIkret · ${model}`;
    $('eleven-connection-status').textContent = status;
    $('eleven-connection-status').dataset.tone = ['missing', 'invalid', 'offline'].includes(state) ? 'error' : '';
    for (const id of ['eleven-voice', 'eleven-model', 'test-eleven-voice']) $(id).disabled = ['missing', 'unverified', 'invalid'].includes(state);
    $('remove-eleven-key').disabled = state === 'missing';
  }

  function previewVoiceTest(targetId, voice) {
    clearTimeout(voiceTestTimer);
    const target = $(targetId);
    const name = voiceNames[voice] || 'Hamed';
    target.dataset.tone = '';
    target.textContent = `Pripremam probu: ${name}…`;
    voiceTestTimer = setTimeout(() => {
      const state = $('eleven-demo-state').value;
      const errors = { quota: 'nema dovoljno ElevenLabs kredita.', invalid: 'API ključ nije prihvaćen.', offline: 'servis trenutno nije dostupan.', missing: 'prvo unesite API ključ.', unverified: 'prvo provjerite vezu.' };
      if (voice === 'efendija' && state !== 'connected') {
        target.dataset.tone = 'error';
        target.textContent = 'Proba Efendije nije uspjela: ' + errors[state];
      } else target.textContent = `Proba glasa ${name} je završena.`;
    }, 650);
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
    $('retry-settings').hidden = !failed;
  }

})();
