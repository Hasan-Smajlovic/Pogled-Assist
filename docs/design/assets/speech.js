(() => {
  'use strict';
  const { GROUPS, ARABIC_LETTERS, SYMBOLS, ARABIC_SPEECH_SYMBOLS, grouped, keyLabel, readScript, writeScript } = ReferenceKeyboard;
  const $ = id => document.getElementById(id);
  const WORDS = ['SELAM', 'JA', 'KAKO', 'MOŽE', 'HVALA', 'ŽELIM', 'VODU', 'VODE', 'VODA', 'RAZGOVARATI', 'ČAJ', 'ĆUP', 'DOĐI', 'DJECA', 'ĐAK', 'DŽEM', 'LJETO', 'NJIVA', 'JUTRO', 'SAM', 'MOLIM', 'TE', 'TREBAM', 'DOBRO', 'DONESI', 'MI', 'JASTUK', 'TELEFON', 'SADA', 'KASNIJE', 'HLADNO', 'TOPLO', "KUR'AN", 'ABDEST', 'NAMAZ', 'DŽUMA', 'HUTBA', 'DŽEMAT', 'IMAM', 'RAMAZAN', 'IFTAR', 'DOVA'];
  const STORE_KEY = 'pogled-assist-design-v1', PAGE_SIZE = 6;
  const gazeDemo = createReferenceGaze();
  let arabic = readScript();
  let activeGroups = arabic ? grouped(ARABIC_LETTERS) : GROUPS;
  const message = $('message');
  const content = $('content');
  const ring = $('gaze-ring');
  const library = loadLibrary();
  let view = 'keyboard';
  let category = null;
  let page = 0;
  let deleting = false;
  let symbols = false;
  let editor = null;
  let savedMessage = '';
  let confirmAction = null;
  let audioContext = null;
  let alarmTimer = null;
  let alarmTone = null;
  let undoWord = null;
  let savedUndo = null;
  let autoSpace = false;
  let lastText = '';
  let previewSpeechTimer;
  let recoveryNoticeTimer;
  const requestedVoiceState = new URLSearchParams(location.search).get('voice-demo');
  const voiceStates = {
    efendija: null,
    quota: ['Nema dovoljno ElevenLabs kredita.', 'Koristi se Prirodni glas.', 'warning'],
    offline: ['ElevenLabs trenutno nije dostupan.', 'Koristi se Prirodni glas.', 'warning'],
    timeout: ['Efendijin glas se predugo priprema.', 'Koristi se Prirodni glas.', 'warning'],
    invalid: ['Provjerite ElevenLabs ključ u Postavkama.', 'Koristi se Prirodni glas.', 'warning'],
    standard: ['Online glasovi trenutno nisu dostupni.', 'Koristi se Standardni glas.', 'warning'],
    cached: ['Koristi se sačuvani Efendijin glas.', 'Ovaj snimak ne troši nove kredite.', 'ready'],
    recovered: ['Efendijin glas je ponovo dostupan.', 'Naredne poruke koriste Efendiju.', 'ready'],
    partial: ['Izgovor nije završen.', 'Za ponavljanje odaberite Izgovori.', 'error'],
  };
  if (Object.hasOwn(voiceStates, requestedVoiceState)) $('voice-demo-state').value = requestedVoiceState;
  const savedPreview = ReferenceDesign.readSession('speech', null);
  if (savedPreview && typeof savedPreview.message === 'string') {
    message.value = savedPreview.message;
    if (['keyboard', 'categories', 'phrases'].includes(savedPreview.view)) view = savedPreview.view;
    category = typeof savedPreview.category === 'string' ? savedPreview.category : null;
    page = Number.isInteger(savedPreview.page) ? savedPreview.page : 0;
    if (savedPreview.editor && ['phrase', 'category', 'answer'].includes(savedPreview.editor.kind)) {
      editor = savedPreview.editor;
      savedMessage = typeof savedPreview.savedMessage === 'string' ? savedPreview.savedMessage : '';
    }
  }
  if (requestedVoiceState && !message.value) message.value = 'TREBAM VODE, MOLIM TE.';
  $('voice-demo-state').addEventListener('change', () => {
    clearTimeout(recoveryNoticeTimer); recoveryNoticeTimer = null;
    renderVoiceNotice();
  });
  $('voice-demo-tracking').addEventListener('change', renderVoiceNotice);
  renderVoiceNotice();

  function renderVoiceNotice() {
    const state = $('voice-demo-state').value;
    const tracking = $('voice-demo-tracking').checked;
    syncRecoveryNotice(state, tracking);
    const notice = tracking
      ? ['Praćenje oba oka je prekinuto', 'pogledajte prema ekranu', 'warning']
      : arabic ? null : voiceStates[state];
    renderNotice(notice, tracking, state);
  }

  function renderNotice(notice, tracking, state) {
    document.querySelector('.message-box').dataset.voiceNotice = String(Boolean(notice));
    $('speech-voice-notice').hidden = !notice;
    if (notice) {
      $('voice-notice-title').textContent = notice[0];
      $('voice-notice-detail').textContent = notice[1];
      $('speech-voice-notice').dataset.tone = notice[2];
      document.querySelector('.voice-notice-mark').textContent = tracking ? '!' : ({ ready: '✓' }[notice[2]] || '!');
    } else {
      const status = { efendija: 'Glas: Efendija' };
      say(arabic && state !== 'none' ? 'Glas: Prirodni · Hamed' : status[state] || '');
    }
  }
  function recoveryVisible(state, tracking) {
    if (tracking) return false;
    if (arabic) return false;
    return state === 'recovered';
  }

  function syncRecoveryNotice(state, tracking) {
    if (!recoveryVisible(state, tracking)) {
      clearTimeout(recoveryNoticeTimer); recoveryNoticeTimer = null;
    } else if (!recoveryNoticeTimer) {
      recoveryNoticeTimer = setTimeout(() => {
        recoveryNoticeTimer = null;
        $('voice-demo-state').value = 'efendija';
        renderVoiceNotice();
      }, 5000);
    }
  }

  $('library-read-error').addEventListener('change', () => { deleting = false; render(); });
  $('single-letter-preview').addEventListener('click', () => {
    activeGroups = (arabic ? ARABIC_LETTERS : GROUPS.flat()).map(letter => [letter]);
    switchView('keyboard');
  });
  $('twelve-letters-preview').addEventListener('click', () => {
    activeGroups = arabic ? grouped(ARABIC_LETTERS) : GROUPS;
    switchView('keyboard'); openLetters(0, 12);
  });
  for (const button of document.querySelectorAll('[data-script-toggle]')) button.addEventListener('click', () => {
    arabic = !arabic; writeScript(arabic);
    activeGroups = arabic ? grouped(ARABIC_LETTERS) : GROUPS;
    if ($('letters-dialog').open) closeDialog($('letters-dialog'));
    symbols = false; render(); renderVoiceNotice(); restoreMessageFocus();
  });

  document.addEventListener('click', event => {
    const button = event.target.closest('button[data-action]');
    if (!button || button.disabled) return;
    if (gazeDemo.isDuplicateClick(button)) return;
    gazeDemo.reset();
    handleAction(button.dataset.action, button.dataset.value);
    restoreMessageFocus();
  });
  message.addEventListener('input', () => {
    const appended = message.value.length === lastText.length + 1 && message.value.startsWith(lastText);
    const moveToEnd = spaceAfterPunctuation(appended);
    const start = moveToEnd ? message.value.length : message.selectionStart;
    const end = moveToEnd ? message.value.length : message.selectionEnd;
    message.value = message.value.toLocaleUpperCase('bs');
    message.setSelectionRange(start, end);
    undoWord = null; autoSpace = false; renderPredictions(); updateSave();
  });

  function spaceAfterPunctuation(appended) {
    const boundary = appended && /[.?]$/.test(message.value);
    const duplicateSpace = appended && repeatedBoundarySpace();
    if (autoSpace && appended) removeSpaceBeforePunctuation();
    if (boundary) message.value += ' ';
    if (duplicateSpace) message.value = lastText;
    return boundary || duplicateSpace;
  }

  function removeSpaceBeforePunctuation() {
    if (/[.,?!]$/.test(message.value)) message.value = lastText.slice(0, -1) + message.value.slice(-1);
  }

  function repeatedBoundarySpace() { return /[.?] $/.test(lastText) && /\s$/.test(message.value); }

  for (const event of ['click', 'keyup', 'select']) message.addEventListener(event, renderPredictions);
  document.addEventListener('keydown', event => {
    if (ignoreKey(event)) return;
    if (messageTab(event)) { event.preventDefault(); return; }
    if (nativeKeyTarget(event)) return;
    if (event.key === 'Backspace') { event.preventDefault(); backspace(); }
    else if (event.key.length === 1) { event.preventDefault(); append(event.key); }
  });
  function messageTab(event) { return event.key === 'Tab' && event.target === message && !$('speech-screen').hidden; }

  function nativeKeyTarget(event) {
    if (event.target.closest('input, summary, .reference-tools, .reference-switcher')) return true;
    return event.key === ' ' && Boolean(event.target.closest('button'));
  }

  function ignoreKey(event) {
    return event.altKey || event.ctrlKey || event.metaKey || Boolean(document.querySelector('dialog[open]'));
  }

  window.addEventListener('focus', () => requestAnimationFrame(restoreMessageFocus));
  for (const dialog of document.querySelectorAll('dialog')) {
    dialog.addEventListener('cancel', event => {
      event.preventDefault();
      if (dialog.id === 'alarm-dialog') stopAlarm();
      else closeDialog(dialog);
    });
  }
  window.addEventListener('pagehide', () => {
    stopAlarm(); window.speechSynthesis?.cancel();
    ReferenceDesign.writeSession('speech', { message: message.value, view, category, page, editor, savedMessage });
  });

  function restoreMessageFocus() {
    if (!document.hasFocus()) return;
    if ($('speech-screen').hidden) return;
    if (document.querySelector('dialog[open]')) return;
    const start = message.selectionStart;
    const end = message.selectionEnd;
    const direction = message.selectionDirection;
    message.focus({ preventScroll: true });
    message.setSelectionRange(start, end, direction);
  }

  function render() {
    gazeDemo.reset();
    renderScript();
    renderViewHeader();
    renderLibraryActions();
    renderKeyboardGrid();
    renderPredictions();
    updateSave();
  }

  function renderScript() {
    for (const button of document.querySelectorAll('[data-script-toggle]')) button.textContent = arabic ? 'Latinica' : 'Arapski';
    message.dir = arabic ? 'rtl' : 'ltr';
    message.style.textAlign = arabic ? 'right' : 'center';
    document.querySelector('.predictions').hidden = arabic;
  }

  function viewTitle() {
    if (editor) return editorTitle();
    if (view === 'phrases') return 'Moje fraze';
    if (view !== 'keyboard') return library.categories.find(item => item.id === category)?.name.toLocaleUpperCase('bs') || 'Kategorije';
    return symbols ? 'Brojevi i znakovi' : 'Odaberite grupu slova';
  }

  function renderViewHeader() {
    for (const [id, target, label] of [['categories-toggle', 'categories', 'Kategorije'], ['phrases-toggle', 'phrases', 'Fraze']]) {
      $(id).textContent = view === target ? 'Tastatura' : label;
      $(id).setAttribute('aria-pressed', String(view === target));
      $(id).disabled = Boolean(editor);
    }
    $('message-label').textContent = editor ? editorTitle() : 'Vaša poruka';
    message.placeholder = editor ? 'Unesite tekst…' : 'Odaberite grupu slova…';
    $('view-title').textContent = viewTitle();
    $('cancel-edit').hidden = !editor;
    $('save').hidden = !editor;
  }

  function renderLibraryActions() {
    const browsing = view !== 'keyboard';
    const libraryBlocked = $('library-read-error').checked;
    $('back').hidden = !browsing || !category;
    $('add').hidden = $('manage').hidden = !browsing || libraryBlocked;
    $('add').textContent = addEntryLabel();
    $('retry-library').hidden = !browsing || !libraryBlocked;
    if (browsing && libraryBlocked) $('view-title').textContent = 'Biblioteka nije učitana';
    $('manage').textContent = deleting ? 'Gotovo' : 'Obriši';
    $('manage').setAttribute('aria-pressed', String(deleting));
  }

  function addEntryLabel() {
    if (view === 'phrases') return 'Dodaj frazu';
    return category ? 'Dodaj odgovor' : 'Dodaj kategoriju';
  }

  function renderKeyboardGrid() {
    const browsing = view !== 'keyboard';
    $('keyboard-toggle').textContent = browsing ? 'Tastatura' : symbols ? 'Grupe slova' : 'Brojevi i znakovi';
    content.replaceChildren();
    content.className = browsing ? 'item-grid' : keyboardGridClass();
    const keyCount = symbols ? grouped(ARABIC_SPEECH_SYMBOLS).length : activeGroups.length;
    const columns = keyboardColumns(keyCount);
    applyKeyboardDirection(browsing, keyCount, columns);
    if (browsing) renderItems();
    else fillKeyboard();
  }

  function applyKeyboardDirection(browsing, keyCount, columns) {
    const rtl = !browsing && arabic;
    content.style.gridTemplateColumns = rtl ? `repeat(${columns}, minmax(0, 1fr))` : '';
    content.style.gridTemplateRows = rtl ? `repeat(${Math.ceil(keyCount / columns)}, minmax(72px, 1fr))` : '';
    content.dir = rtl ? 'rtl' : 'ltr';
  }

  function keyboardGridClass() {
    if (symbols) return 'key-grid symbols';
    return activeGroups.length >= 20 ? 'key-grid dense' : 'key-grid';
  }

  function keyboardColumns(count) {
    let columns = count <= 1 ? 1 : count <= 8 ? 2 : Math.min(6, Math.ceil(count / 5));
    if (!symbols) columns = Math.max(columns, Math.ceil(count / 5));
    return columns;
  }

  function fillKeyboard() {
    $('paging').hidden = true;
    if (symbols && arabic) grouped(ARABIC_SPEECH_SYMBOLS).forEach((keys, index) => content.append(makeButton(keys.map(keyLabel).join(' '), 'symbol-group', index, 'group')));
    else if (symbols) SYMBOLS.forEach(value => content.append(makeButton(value, 'symbol', value, 'group')));
    else activeGroups.forEach((letters, index) => content.append(makeButton(letters.join(' '), 'group', index, 'group')));
  }

  const actionHandlers = {
    'group': value => { openLetters(Number(value)); },
    'symbol-group': value => { openLetters(Number(value), 0, grouped(ARABIC_SPEECH_SYMBOLS)); },
    'letter': value => { append(value); closeDialog($('letters-dialog')); },
    'symbol': value => { append(value); },
    'close-letters': value => { closeDialog($('letters-dialog')); },
    'word': value => { appendWord(value, true); },
    'undo-word': value => { if (undoWord) { message.value = undoWord.text; autoSpace = undoWord.autoSpace; undoWord = null; renderPredictions(); updateSave(); } },
    'space': value => { append(' '); },
    'backspace': value => { backspace(); },
    'clear': value => { if (message.value) askConfirm('Obrisati sav tekst?', editor ? 'Obrisat će se samo novi unos. Vaša poruka za razgovor ostaje sačuvana.' : 'Cijela poruka bit će obrisana.', 'Obriši tekst', () => { message.value = ''; renderPredictions(); updateSave(); say('Tekst je obrisan.'); }); },
    'speak': value => { speak(); },
    'stop-speech': value => { clearTimeout(previewSpeechTimer); window.speechSynthesis?.cancel(); playback(false); say('Govor je zaustavljen.'); },
    'categories': value => { switchView(view === 'categories' ? 'keyboard' : 'categories'); },
    'phrases': value => { switchView(view === 'phrases' ? 'keyboard' : 'phrases'); },
    'keyboard-toggle': value => { if (view !== 'keyboard') switchView('keyboard');
        else { symbols = !symbols; render(); } },
    'back': value => { category = null; page = 0; deleting = false; render(); },
    'previous': value => { page--; renderItems(); },
    'next': value => { page++; renderItems(); },
    'manage': value => { deleting = !deleting; render(); say(deleting ? 'Odaberite stavku koju želite obrisati.' : ''); },
    'item': value => { selectItem(value); },
    'add': value => { startEditor(); },
    'cancel-edit': value => { finishEditor(false); },
    'save': value => { finishEditor(true); },
    'retry-library': value => { $('library-read-error').checked = false; category = null; page = 0; render(); say('Biblioteka je učitana.'); },
    'cancel-confirm': value => { closeDialog($('confirm-dialog')); confirmAction = null; },
    'confirm': value => { {
        const actionToRun = confirmAction;
        confirmAction = null;
        closeDialog($('confirm-dialog'));
        actionToRun?.();

      } },
    'alarm': value => { startAlarm(); },
    'stop-alarm': value => { stopAlarm(); },
    'sleep': value => { window.speechSynthesis?.cancel(); openDialog($('sleep-screen')); },
    'wake': value => { closeDialog($('sleep-screen')); say('Možete nastaviti.'); },
    'exit': value => { openDialog($('exit-dialog')); },
    'cancel-exit': value => { closeDialog($('exit-dialog')); },
    'leave-speech': value => { window.speechSynthesis?.cancel(); closeDialog($('exit-dialog')); openDialog($('speech-closed-screen')); },
    'quit-app': value => { window.speechSynthesis?.cancel(); closeDialog($('exit-dialog')); openDialog($('closed-screen')); },
    'reopen-speech': value => { closeDialog($('speech-closed-screen')); },
    'reopen': value => { closeDialog($('closed-screen')); },
  };

  function handleAction(action, value) { actionHandlers[action]?.(value); }

  function openLetters(index, previewSize = 0, groups = activeGroups) {
    const letters = previewSize ? groups.flat().slice(0, previewSize) : groups[index];
    if (!letters) return;
    $('letters').classList.toggle('wide', letters.length >= 6);
    $('letters-dialog').classList.toggle('compact', letters.length >= 12);
    $('letters-title').textContent = symbols ? 'Odaberite znak' : 'Odaberite slovo';
    $('letters').dir = 'ltr';
    $('letters').replaceChildren(...letters.map(letter => makeButton(keyLabel(letter), 'letter', letter)));
    $('letters').append(makeButton(letters.length >= 12 ? 'Nazad' : 'Nazad na grupe', 'close-letters', '', 'back'));
    if (arabic) {
      const columns = letters.length + 1 <= 6 ? 3 : 4;
      [...$('letters').children].forEach((button, index) => {
        const row = Math.floor(index / columns);
        const rowKeys = Math.min(columns, letters.length - row * columns);
        button.style.gridRow = String(row + 1);
        button.style.gridColumn = String(index === letters.length ? index % columns + 1 : rowKeys - index % columns);
      });
    }
    openDialog($('letters-dialog'));
  }

  function switchView(nextView) {
    view = nextView;
    category = null;
    page = 0;
    deleting = false;
    symbols = false;
    render();
    say('');
  }

  function currentItems() {
    if (view === 'phrases') return library.phrases;
    if (!category) return library.categories;
    return library.categories.find(item => item.id === category)?.items || [];
  }

  function renderItems() {
    gazeDemo.reset();
    const items = currentItems();
    const pages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
    page = Math.min(Math.max(page, 0), pages - 1);
    content.replaceChildren();
    for (const item of items.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)) {
      const button = makeButton((item.name || item.text).toLocaleUpperCase('bs'), 'item', item.id, deleting ? 'item danger' : 'item');
      if (deleting || item.items) {
        const hint = document.createElement('small');
        hint.textContent = deleting ? 'Obriši' : `Odgovori: ${item.items.length}`;
        button.append(hint);
      }
      content.append(button);
    }
    if (!items.length) {
      const empty = document.createElement('p');
      empty.className = 'empty';
      empty.textContent = 'Lista je prazna. Odaberite Dodaj za novi unos.';
      content.append(empty);
    }
    $('manage').disabled = !items.length;
    $('paging').hidden = pages === 1;
    $('page-number').textContent = `${page + 1} / ${pages}`;
    document.querySelector('[data-action="previous"]').disabled = page === 0;
    document.querySelector('[data-action="next"]').disabled = page === pages - 1;
  }

  function selectItem(id) {
    const item = currentItems().find(item => item.id === id);
    if (!item) return;
    if (deleting) {
      const name = item.name || item.text;
      askConfirm('Obrisati ovu stavku?', item.items ? `Kategorija „${name}” i svi njeni odgovori bit će obrisani.` : `„${name}” će biti obrisano iz liste.`, 'Obriši', () => {
        const items = currentItems();
        items.splice(items.findIndex(entry => entry.id === id), 1);
        const stored = saveLibrary();
        render();
        say(stored ? 'Stavka je obrisana.' : 'Obrisano za ovaj pregled. Lokalno čuvanje nije dostupno.');
      });
    } else if (item.items) {
      category = id;
      page = 0;
      render();
    } else {
      appendWord(item.text);
      say('Dodano u poruku. Odaberite Izgovori za čitanje.');
    }
  }

  function startEditor() {
    editor = { kind: view === 'phrases' ? 'phrase' : category ? 'answer' : 'category', view, category, page };
    savedMessage = message.value;
    savedUndo = { undoWord, autoSpace };
    undoWord = null; autoSpace = false;
    message.value = '';
    view = 'keyboard';
    deleting = false;
    symbols = false;
    render();
    say('Unesite tekst pomoću grupa slova, zatim odaberite Sačuvaj.');
  }

  function editorTitle() {
    return editor.kind === 'category' ? 'Nova kategorija' : editor.kind === 'answer' ? 'Novi odgovor' : 'Nova fraza';
  }

  function finishEditor(save) {
    if (!editor) return;
    const text = message.value.trim().replace(/\s+/g, ' ').toLocaleUpperCase('bs');
    if (save && !text) { say('Prvo unesite tekst.'); return; }
    const destination = editorDestination();
    if (save && duplicateEntry(destination, text)) {
      say('Ova stavka već postoji. Unesite drugi tekst ili odaberite Odustani.');
      return;
    }
    let stored = true;
    if (save) {
      destination.push(editor.kind === 'category' ? { id: makeId(), name: text, items: [] } : { id: makeId(), text });
      stored = saveLibrary();
    }
    restoreEditor(save, destination);
    say(editorResult(save, stored));
  }

  function editorResult(save, stored) {
    if (!save) return 'Dodavanje je otkazano. Vaša poruka je vraćena.';
    return stored ? 'Sačuvano. Vaša poruka je vraćena.' : 'Dodano za ovaj pregled. Lokalno čuvanje nije dostupno.';
  }

  function editorDestination() {
    const lists = { phrase: library.phrases, category: library.categories };
    return lists[editor.kind] || library.categories.find(item => item.id === editor.category).items;
  }

  function duplicateEntry(destination, text) {
    return destination.some(item => (item.name || item.text).toLocaleLowerCase('bs') === text.toLocaleLowerCase('bs'));
  }

  function restoreEditor(save, destination) {
    view = editor.view;
    category = editor.category;
    page = save ? Math.floor((destination.length - 1) / PAGE_SIZE) : editor.page;
    message.value = savedMessage;
    undoWord = savedUndo?.undoWord || null; autoSpace = savedUndo?.autoSpace || false;
    savedUndo = null;
    savedMessage = '';
    editor = null;
    render();
  }


  function append(value) {
    if (value === ' ' && /[.?] $/.test(message.value)) return;
    if (autoSpace && /^[.,?!]$/.test(value)) message.value = message.value.slice(0, -1);
    undoWord = null; autoSpace = false;
    message.value += value.toLocaleUpperCase('bs');
    if (/^[.?]$/.test(value)) message.value += ' ';
    message.scrollLeft = message.scrollWidth;
    renderPredictions();
    updateSave();
  }

  function appendWord(word, complete = false) {
    undoWord = complete ? { text: message.value, autoSpace } : null;
    let prefix = message.value;
    if (complete) prefix = completedWordPrefix(prefix);
    if (prefix && !/\s$/.test(prefix)) prefix += ' ';
    message.value = `${prefix}${word.toLocaleUpperCase('bs')} `;
    autoSpace = complete;
    renderPredictions();
    updateSave();
  }

  function completedWordPrefix(prefix) {
    if (!prefix || /\s$/.test(prefix)) return prefix;
    return prefix.replace(/[a-zčćđšž]+$/iu, '');
  }

  function backspace() {
    undoWord = null; autoSpace = false;
    const value = message.value;
    const end = value.slice(-2).toLocaleUpperCase('bs');
    message.value = value.slice(0, ['DŽ', 'LJ', 'NJ'].includes(end) ? -2 : -1);
    renderPredictions();
    updateSave();
  }

  function updateSave() { $('save').disabled = !message.value.trim(); lastText = message.value; $('undo-word').disabled = !undoWord; }

  function renderPredictions() {
    gazeDemo.blockCurrent();
    gazeDemo.reset();
    const partial = message.value.match(/[a-zčćđšž]+$/iu)?.[0].toLocaleLowerCase('bs') || '';
    const matches = predictionMatches(partial);
    if (!$('predictions').children.length) for (let index = 0; index < 5; index++) $('predictions').append(makeButton('·', 'word', '', 'word'));
    for (let index = 0; index < 5; index++) {
      const word = matches[index];
      const button = $('predictions').children[index];
      renderPrediction(button, word);
    }
    $('undo-word').disabled = !undoWord;
  }

  function renderPrediction(button, word) {
    button.textContent = word || '·'; button.dataset.value = word || '';
    button.disabled = !word;
    button.setAttribute('aria-label', word || 'Nema prijedloga');
  }

  function predictionMatches(partial) {
    if (!predictionsEnabled(partial)) return [];
    if (!partial) return /ŽELIM\s+$/iu.test(message.value) ? ['VODU', 'RAZGOVARATI', 'ČAJ', 'KAFU', 'ODMORITI'] : WORDS;
    const letters = partial.match(/dj|./gu) || [];
    const variants = { dj: '(?:dj|đ)', c: '[cčć]', d: '[dđ]', s: '[sš]', z: '[zž]' };
    const pattern = new RegExp('^' + letters.map(letter => variants[letter] || letter).join(''), 'iu');
    return WORDS.filter(word => pattern.test(word));
  }

  function predictionsEnabled(partial) {
    if (arabic || editor?.kind === 'category') return false;
    if (!cursorAtEnd()) return false;
    return Boolean(partial || !message.value || /[\s.,?!]$/.test(message.value));
  }

  function cursorAtEnd() {
    return message.selectionStart === message.value.length && message.selectionEnd === message.value.length;
  }

  function playback(active) {
    $('speak-button').dataset.playing = String(active);
    $('speak-button').textContent = active ? 'Zaustavi' : 'Izgovori';
    $('speech-progress').hidden = !active;
  }
  function speak() {
    if ($('speak-button').dataset.playing === 'true') { clearTimeout(previewSpeechTimer); window.speechSynthesis?.cancel(); playback(false); say('Govor je zaustavljen.'); return; }
    const text = message.value.trim();
    if (!text) { say('Prvo sastavite poruku.'); return; }
    if ($('voice-demo-state').value !== 'none') { previewSpeech(); return; }
    browserSpeech(text);
  }

  function browserSpeech(text) {
    if (!('speechSynthesis' in window)) { say('Izgovor nije podržan u ovom pregledniku.'); return; }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = arabic ? 'ar-SA' : 'bs-BA';
    const voice = window.speechSynthesis.getVoices().find(voice => (arabic ? /^ar(?:-|$)/i : /^bs(?:-|$)/i).test(voice.lang));
    if (voice) utterance.voice = voice;
    playback(true);
    utterance.onstart = () => say('Poruka se izgovara.');
    utterance.onend = () => { playback(false); say('Čitanje je završeno.'); };
    utterance.onerror = () => { playback(false); say('Govor nije uspio. Pokušajte ponovo.'); };
    say('Pokrećem govor.');
    window.speechSynthesis.speak(utterance);
  }

  function previewSpeech() {
      clearTimeout(previewSpeechTimer);
      say('Pripremam govor…');
      playback(true);
      previewSpeechTimer = setTimeout(() => { say('Poruka se izgovara.'); previewSpeechTimer = setTimeout(() => { playback(false); say('Čitanje je završeno.'); renderVoiceNotice(); }, 2000); }, 650);
  }

  function askConfirm(title, copy, label, action) {
    $('confirm-title').textContent = title;
    $('confirm-copy').textContent = copy;
    $('confirm-button').textContent = label;
    confirmAction = action;
    openDialog($('confirm-dialog'));
  }

  function openDialog(dialog) {
    gazeDemo.reset();
    document.querySelector('.reference-tools').open = false;
    dialog.showModal();
  }

  function closeDialog(dialog) {
    gazeDemo.reset();
    document.body.append(ring);
    dialog.close();
    requestAnimationFrame(restoreMessageFocus);
  }

  async function startAlarm() {
    window.speechSynthesis?.cancel();
    $('alarm-copy').textContent = 'Pokrećem zvučni signal…';
    openDialog($('alarm-dialog'));
    try {
      const ready = prepareAlarmAudio();
      await ready;
      if (!$('alarm-dialog').open) return;
      if (audioContext.state !== 'running') throw new Error('Audio blocked');
      $('alarm-copy').textContent = 'Zvučni signal se ponavlja dok ga ne zaustavite.';
      beep();
      alarmTimer = window.setInterval(beep, 1300);
    } catch {
      $('alarm-copy').textContent = 'Zvuk nije dostupan u ovom pregledniku. Za probu zvuka ponovo otvorite Alarm klikom.';
    }
  }

  function prepareAlarmAudio() {
      const Audio = window.AudioContext || window.webkitAudioContext;
      if (!Audio) throw new Error('Audio unavailable');
      audioContext ||= new Audio();
      const ready = audioContext.resume();
      if (audioContext.state !== 'running') $('alarm-copy').textContent = 'Zvuk čeka dozvolu preglednika. Ako se ne čuje, zaustavite alarm i ponovo ga otvorite klikom.';
      return ready;
  }

  function beep() {
    const start = audioContext.currentTime;
    const tone = audioContext.createOscillator();
    const volume = audioContext.createGain();
    alarmTone = tone;
    tone.onended = () => {
      tone.disconnect();
      volume.disconnect();
      if (alarmTone === tone) alarmTone = null;
    };
    tone.frequency.value = 740;
    tone.connect(volume);
    volume.connect(audioContext.destination);
    volume.gain.setValueAtTime(0, start);
    volume.gain.linearRampToValueAtTime(.15, start + .03);
    volume.gain.setValueAtTime(.15, start + .35);
    volume.gain.linearRampToValueAtTime(0, start + .5);
    tone.start(start);
    tone.stop(start + .51);
  }

  function stopAlarm() {
    clearInterval(alarmTimer);
    alarmTimer = null;
    alarmTone?.stop();
    alarmTone = null;
    audioContext?.suspend();
    if ($('alarm-dialog').open) closeDialog($('alarm-dialog'));
  }

  function makeButton(label, action, value = '', className = '') {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.className = className;
    button.dataset.action = action;
    button.dataset.value = String(value);
    return button;
  }

  function say(text) { $('status').textContent = text; }
  function makeId() { return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`; }

  function loadLibrary() {
    try {
      const stored = JSON.parse(localStorage.getItem(STORE_KEY));
      const validItem = item => item && typeof item.id === 'string' && typeof item.text === 'string';
      if (validLibrary(stored, validItem)) return stored;
    } catch {}
    const category = (id, name, texts) => ({ id, name, items: texts.map((text, index) => ({ id: `${id}-${index}`, text })) });
    return {
      categories: [
        category('needs', 'Trebam', ['Trebam vode', 'Namjesti mi jastuk', 'Trebam lijek', 'Pomozi mi da se okrenem', 'Hladno mi je', 'Trebam u toalet']),
        category('answers', 'Brzi odgovor', ['Da', 'Ne', 'Možda', 'Hvala', 'Molim te', 'Nisam razumio']),
        category('feelings', 'Kako se osjećam', ['Dobro sam', 'Boli me', 'Umoran sam', 'Nervozan sam', 'Sretan sam', 'Neugodno mi je']),
        category('people', 'Ljudi', ['Pozovi Hasana', 'Želim porodicu', 'Pozovi medicinsku sestru', 'Želim razgovarati', 'Ko je ovdje?', 'Ostani sa mnom'])
      ],
      phrases: ['Trebam vode', 'Hvala ti', 'Pozovi Hasana', 'Namjesti mi jastuk'].map((text, index) => ({ id: `phrase-${index}`, text }))
    };
  }

  function validLibrary(stored, validItem) {
    if (!stored) return false;
    if (!Array.isArray(stored.categories)) return false;
    if (!Array.isArray(stored.phrases)) return false;
    return stored.phrases.every(validItem) && stored.categories.every(item => validCategory(item, validItem));
  }

  function validCategory(item, validItem) {
    if (!item) return false;
    if (typeof item.id !== 'string') return false;
    if (typeof item.name !== 'string') return false;
    return Array.isArray(item.items) && item.items.every(validItem);
  }

  function saveLibrary() {
    if ($('library-read-error').checked) return false;
    try { localStorage.setItem(STORE_KEY, JSON.stringify(library)); return true; }
    catch { return false; }
  }

  render();
  requestAnimationFrame(restoreMessageFocus);
})();
