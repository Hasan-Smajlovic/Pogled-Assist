(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let learnedWords = ['ĆEVAPI', 'DŽEZ', 'KAHVA', 'LJETO', 'NJIVA', 'ŠETNJA'];
  let selectedWord = null;
  let arabic = ReferenceKeyboard.readScript();
  function renderScript() {
    $('settings-script-preview').textContent = arabic ? 'Arapski' : 'Latinica';
    $('voice-hint').textContent = arabic ? 'Arapski koristi prirodni muški glas Hamed. Potreban je internet. Izbor bosanskog glasa ostaje sačuvan.' : 'Standardni glas koristi eSpeak NG. Prirodni glas koristi Microsoft Edge bs-BA-GoranNeural.';
    $('voice-preview').textContent = arabic ? 'Prirodni · Hamed' : 'Standardni';
    $('voice-preview').disabled = arabic;
  }
  $('settings-script-preview').addEventListener('click', () => {
    arabic = !arabic;
    ReferenceKeyboard.writeScript(arabic);
    renderScript();
  });
  $('show-tracking-feedback').checked = ReferenceDesign.readSession('feedback', true);
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
  renderScript(); renderFeedbackLink(); renderStorageState(); renderLearning();
  const initialTab = location.hash.slice(1);
  if (['general-settings', 'gaze-settings', 'speech-settings', 'learning-settings'].includes(initialTab)) handleSettingsAction(initialTab);
  function handleSettingsAction(action) {
    if (action === 'retry-settings') {
      $('settings-save-error').checked = false; renderStorageState();
      $('settings-status').textContent = 'Postavke su sačuvane.'; return;
    }
    if (['general-settings', 'gaze-settings', 'speech-settings', 'learning-settings'].includes(action)) {
      for (const id of ['general-settings', 'gaze-settings', 'speech-settings', 'learning-settings']) $(id).hidden = id !== action;
      for (const button of document.querySelectorAll('.settings-nav [data-settings-action]')) button.setAttribute('aria-pressed', String(button.dataset.settingsAction === (action === 'learning-settings' ? 'speech-settings' : action)));
      if (action === 'learning-settings') renderLearning();
      return;
    }
    if (action === 'forget-word' && selectedWord) {
      if ($('learning-demo-state').value === 'write') {
        $('learning-status').textContent = 'Učenje nije sačuvano. Pokušajte ponovo.';
        $('retry-learning').disabled = false;
      } else {
        learnedWords = learnedWords.filter(word => word !== selectedWord);
        selectedWord = null; renderLearning();
        $('learning-status').textContent = 'Riječ je zaboravljena. Vaša poruka je sačuvana.';
      }
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
      status.textContent = 'Dostupna je verzija v0.2.0. Trenutno koristite v0.1.0.';
      pageStatus.textContent = 'Dostupno je ažuriranje na v0.2.0.';
      installButton.hidden = false;
    } else if (action === 'install-update') {
      checkButton.disabled = true;
      installButton.disabled = true;
      status.textContent = 'Pokrećem updater. Aplikacija će se zatvoriti i pokrenuti nakon instalacije.';
      pageStatus.textContent = 'Pokrećem ažuriranje.';
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
    $('settings-save-note').textContent = failed ? 'Postavke nisu sačuvane. Važe do zatvaranja aplikacije.' : 'Promjene se primjenjuju i čuvaju automatski.';
    $('retry-settings').hidden = !failed;
  }

})();
