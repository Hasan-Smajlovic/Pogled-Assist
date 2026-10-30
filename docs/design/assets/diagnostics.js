(() => {
  'use strict';
  const diagEl = id => document.getElementById(id);
  const query = new URLSearchParams(location.search);
  const origin = ['settings', 'gaze-check'].includes(query.get('return')) ? query.get('return') : 'settings';
  const reasons = {
    completed: ['Završeno', 'Isteklo je izabrano vrijeme snimanja.'],
    manual: ['Završeno', 'Snimanje je zaustavljeno ručno.'],
    'size-limit': ['Limit prostora', 'Snimanje je završeno na 32 MiB. Događaji nakon toga nisu zabilježeni.'],
    dropped: ['Podaci s prekidima', 'Izostavljena su 23 događaja zbog opterećenog reda zapisivanja.'],
    interrupted: ['Prekinuto', 'Aplikacija je zatvorena prije isteka vremena. Dostupan je sačuvani dio.'],
    'write-error': ['Greška zapisivanja', 'Zapisivanje je stalo zbog greške. Dostupan je samo prethodno sačuvani dio.'],
    unreadable: ['Nečitljiv snimak', 'Format ili sadržaj snimka nije moguće pročitati. Izvoz nije dostupan.'],
  };
  const checks = {
    'provjera-015': '22.10.2026. · 14:32 · Oba oka · Završeno',
    'provjera-014': '21.10.2026. · 17:45 · Oba oka uz kratke prekide · Završeno',
    'provjera-013': '21.10.2026. · 17:38 · Jedno oko je dovoljno (probno) · Prekinuto',
  };
  let tab = 'new';
  let minutes = 2;
  let selectedId = null;
  let mode = '';
  let pendingExport = null;
  let status = '';

  function setText(id, value) {
    const element = diagEl(id);
    if (element.textContent !== value) element.textContent = value;
  }

  function selectTab(name, focus = false) {
    tab = name;
    for (const value of ['new', 'history']) {
      const button = diagEl('diagnostics-tab-' + value);
      button.setAttribute('aria-selected', String(value === tab));
      button.tabIndex = value === tab ? 0 : -1;
      diagEl('diagnostics-' + value).hidden = value !== tab;
      if (focus && value === tab) button.focus();
    }
    status = '';
    render();
  }

  function selectedItem() { return ReferenceRecording.state().items.find(item => item.id === selectedId); }

  function render() {
    const value = ReferenceRecording.state();
    const finishing = Boolean(value.active?.stoppingUntil);
    renderNew(value);
    renderHistory(value);
    const primary = diagEl('diagnostics-primary');
    const button = primaryState(value, finishing);
    primary.className = button.className;
    primary.disabled = button.disabled;
    primary.textContent = button.text;
    diagEl('diagnostics-return').textContent = origin === 'gaze-check' ? 'Nazad na provjeru' : 'Vrati se u Postavke';
    setText('diagnostics-status', status || defaultStatus(value, finishing));
  }

  function primaryState(value, finishing) {
    const className = value.active && tab === 'new' ? 'danger' : 'primary';
    const disabled = finishing || (tab === 'history' && !selectedItem()?.readable);
    if (finishing) return { className, disabled, text: 'Završavam snimak…' };
    if (tab === 'history') return { className, disabled, text: 'Izvezi ZIP' };
    return { className, disabled, text: value.active ? 'Zaustavi snimanje' : 'Pokreni snimanje' };
  }
  function defaultStatus(value, finishing) {
    if (finishing) return 'Čekam potvrdu čuvanja. Novi snimak još nije dostupan.';
    if (value.active) return 'Možete zatvoriti ovaj prozor; snimanje nastavlja raditi.';
    if (tab === 'history') return 'Izvoz pravi lokalni ZIP. Podaci se ne šalju automatski.';
    return 'Izaberite trajanje, zatim pokrenite snimanje.';
  }

  function renderNew(value) {
    const active = value.active;
    const finishing = Boolean(active?.stoppingUntil);
    const elapsed = active ? Math.max(0, ((active.stopped || Date.now()) - active.started) / 1000) : 0;
    const duration = (active ? active.minutes : minutes) * 60;
    renderDuration(active, elapsed, duration, finishing);
    renderLogging();
    renderPersistence(value);
    renderRecordingState(active, finishing);
  }
  function renderPersistence(value) {
    const text = value.persistenceFailure
      ? 'Prekidi čuvanja: opći logovi · Greška zapisivanja · Početak 28.10.2026. 14:32:05 · Oporavak: još traje. Raniji prekid: ručni snimak · Greška završnog zapisa · Početak 28.10.2026. 14:30:00 · Oporavak 28.10.2026. 14:31:00. Prikaz je skraćen na posljednja 64 prekida.'
      : 'Nema zabilježenih prekida čuvanja.';
    setText('persistence-history', text);
  }
  function renderDuration(active, elapsed, duration, finishing) {
    for (const button of document.querySelectorAll('[data-duration]')) {
      button.disabled = Boolean(active) || finishing;
      button.setAttribute('aria-pressed', String(Number(button.dataset.duration) === (active ? active.minutes : minutes)));
    }
    diagEl('recording-remaining').textContent = ReferenceRecording.clock(duration - elapsed);
    diagEl('recording-size').textContent = (active ? (elapsed * .085).toFixed(1).replace('.', ',') : '0') + ' MiB';
    diagEl('recording-progress').max = duration;
    diagEl('recording-progress').value = elapsed;
  }
  function renderLogging() {
    const logging = diagEl('diagnostics-logging-preview').checked;
    diagEl('recording-logging').textContent = logging ? 'Uključeno' : 'Isključeno';
    diagEl('recording-logging-copy').textContent = logging ? 'Obično zapisivanje ostaje uključeno i nakon završetka ovog snimka.' : 'Ručno snimanje radi i kada je opće zapisivanje isključeno. Ta postavka ostaje isključena.';
    diagEl('recording-policy').textContent = 'Trenutni režim: ' + ReferenceEyePolicy.label() + ' · Pauza 250 ms · Zadržavanje 850 ms';
  }
  function renderRecordingState(active, finishing) {
    const phase = finishing ? 'finishing' : active ? 'recording' : 'ready';
    const display = {
      finishing: { tone: 'ready', mark: '◷', title: 'Završavam i čuvam snimak', copy: 'Izvoz će biti dostupan nakon potvrde čuvanja.' },
      recording: { tone: 'recording', mark: '●', title: 'Snimanje je u toku', copy: 'Vratite se u aplikaciju i ponovite problem. Ovaj prozor možete zatvoriti.' },
      ready: { tone: 'ready', mark: '○', title: 'Spremno za snimanje', copy: 'Kraj po isteku vremena. Možete zaustaviti i ranije.' },
    }[phase];
    const box = diagEl('recording-state');
    box.dataset.tone = display.tone;
    box.querySelector('.recording-state-mark').textContent = display.mark;
    setText('recording-state-title', display.title);
    setText('recording-state-copy', display.copy);
  }

  function renderHistory(value) {
    if (!value.items.some(item => item.id === selectedId)) selectedId = value.items[0]?.id || null;
    renderRecordingList(value.items);
    diagEl('recording-empty').hidden = value.items.length > 0;
    const item = value.items.find(entry => entry.id === selectedId);
    diagEl('recording-detail').hidden = !item;
    diagEl('recording-no-detail').hidden = Boolean(item);
    if (!item) return;
    renderRecordingDetail(item);
    renderRecordingContext(item);
    diagEl('recording-check-result').disabled = !item.readable;
    renderPackage();
  }
  function renderRecordingList(items) {
    const list = diagEl('recording-list');
    const ids = items.map(item => item.id).join('|');
    if (list.dataset.ids !== ids) {
      list.replaceChildren();
      for (const item of items) {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.recording = item.id;
        const title = document.createElement('strong');
        title.textContent = ReferenceRecording.date(item.started);
        const detail = document.createElement('small');
        detail.textContent = reasons[item.reason][0] + ' · ' + item.size.toFixed(1).replace('.', ',') + ' MiB · Simulacija';
        button.append(title, detail);
        button.addEventListener('click', () => {
          selectedId = item.id;
          status = '';
          diagEl('recording-check-result').value = '';
          render();
        });
        list.append(button);
      }
      list.dataset.ids = ids;
    }
    for (const button of list.children) button.setAttribute('aria-pressed', String(button.dataset.recording === selectedId));
  }
  function renderRecordingDetail(item) {
    diagEl('recording-detail-title').textContent = reasons[item.reason][0];
    diagEl('recording-detail-date').textContent = ReferenceRecording.date(item.started) + ' · ' + item.id;
    diagEl('recording-detail-duration').textContent = item.readable ? ReferenceRecording.clock(item.seconds) : 'Nedostupno';
    diagEl('recording-detail-size').textContent = item.size.toFixed(1).replace('.', ',') + ' MiB';
    diagEl('recording-detail-policy').textContent = item.readable ? ReferenceRecording.policy(item.policy) : 'Nepoznato';
    renderRecordingHealth(item);
    diagEl('recording-detail-context').textContent = item.readable ? 'Primjer okruženja: v0.5.0 · revizija 7f3a2c1… · Windows paket · Stream Engine x86 · 1280 × 720 logički / 1920 × 1080 fizički · 150%' : 'Tehnički kontekst nije dostupan. Snimak ostaje sačuvan i označen kao nečitljiv.';
  }
  function renderRecordingHealth(item) {
    const health = diagEl('recording-detail-health');
    health.dataset.tone = !item.readable || item.reason === 'write-error' ? 'error' : ['size-limit', 'dropped', 'interrupted'].includes(item.reason) ? 'warning' : 'normal';
    setText('recording-detail-health', reasons[item.reason][1] + (['completed', 'manual'].includes(item.reason) ? ' Početak i kraj su prisutni; nisu prijavljeni izostavljeni događaji ili greške zapisivanja.' : ' Potpunost podataka nije potvrđena.'));
  }
  function renderRecordingContext(item) {
    const context = diagEl('recording-context-details');
    context.replaceChildren();
    if (item.readable) {
      for (const [name, value] of [
        ['Početni režim', ReferenceRecording.policy(item.policy)],
        ['Početna pauza / zadržavanje', '250 / 850 ms'],
        ['Čuvanje pri gubitku oka / uz rub', '150 / 120 ms · primjenjuje se prema režimu'],
        ['Početna pauza između radnji', '350 ms'],
        ['Uglađivanje / radijus pokazivača', '0,05 / 52 px'],
        ['Aplikacija / izvor', 'v0.5.0 · Windows paket · izmišljeni primjer'],
        ['Puna revizija', '7f3a2c10000000000000000000000000000000000'],
        ['Lokalne izmjene pri izradi', 'Nema · izmišljeni primjer'],
        ['Backend / SDK', 'Stream Engine x86 / 2.2.3.3008'],
        ['Model / firmware', 'Tobii Eye Tracker 4C / firmware nije dostupan'],
        ['Prikaz', '1280 × 720 logičkih px / 1920 × 1080 fizičkih px · 150%'],
        ['Izvor podataka', 'Simulacija · nije mjerenje Tobii uređaja'],
        ['Promjene tokom snimanja', 'Nema u ovom primjeru; stvarne promjene imaju vrijeme događaja.'],
      ]) {
        const label = document.createElement('dt'); label.textContent = name;
        const detail = document.createElement('dd'); detail.textContent = value;
        context.append(label, detail);
      }
    }
  }

  function renderPackage() {
    const check = diagEl('recording-check-result').value;
    diagEl('recording-check-copy').textContent = check ? 'Dodat će se zaseban rezultat: ' + checks[check] + ' · Simulacija. Datum i režim testa ostaju navedeni uz rezultat.' : 'Rezultat se ne dodaje automatski. Možete izabrati i prekinutu provjeru.';
    diagEl('recording-files').querySelectorAll('[data-check-file]').forEach(item => item.remove());
    if (check) {
      for (const name of ['provjera/rezultat.json', 'provjera/izvjestaj.txt']) {
        const item = document.createElement('li');
        item.dataset.checkFile = '';
        item.textContent = name + ' — izabrani rezultat provjere';
        diagEl('recording-files').append(item);
      }
    }
  }

  function close() {
    ReferenceDesign.open(origin, origin === 'gaze-check' ? { resume: 'diagnostics' } : {});
  }

  function applyPreview(kind) {
    mode = kind;
    selectedId = null;
    diagEl('recording-check-result').value = '';
    ReferenceRecording.preview(kind);
    wasActive = Boolean(ReferenceRecording.state().active);
    selectTab(['ready', 'recording', 'recording-error', 'finishing'].includes(kind) ? 'new' : 'history');
  }

  for (const name of ['new', 'history']) {
    const button = diagEl('diagnostics-tab-' + name);
    button.addEventListener('click', () => selectTab(name));
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      selectTab(event.key === 'Home' ? 'new' : event.key === 'End' ? 'history' : tab === 'new' ? 'history' : 'new', true);
    });
  }
  for (const button of document.querySelectorAll('[data-duration]')) button.addEventListener('click', () => { minutes = Number(button.dataset.duration); render(); });
  diagEl('diagnostics-primary').addEventListener('click', () => {
    if (tab === 'new') {
      if (ReferenceRecording.state().active) ReferenceRecording.stop();
      else { mode = ''; ReferenceRecording.start(minutes); wasActive = true; }
      status = '';
      render();
      return;
    }
    const item = selectedItem();
    if (!item?.readable) return;
    pendingExport = { id: item.id, check: diagEl('recording-check-result').value };
    diagEl('recording-export-copy').textContent = 'Snimak: ' + ReferenceRecording.date(item.started) + (pendingExport.check ? '. Dodat je izabrani rezultat provjere.' : '. Bez dodatnog rezultata provjere.');
    diagEl('recording-export-filename').value = 'pogled-dijagnostika-' + item.id + '.zip';
    diagEl('recording-export-dialog').showModal();
  });
  diagEl('recording-export-cancel').addEventListener('click', () => diagEl('recording-export-dialog').close());
  diagEl('recording-export-save').addEventListener('click', () => {
    const failed = mode === 'export-error';
    status = failed ? 'Izvoz snimka ' + pendingExport.id + ' nije uspio. Snimak ostaje dostupan; pokušajte ponovo.' : 'ZIP je izvezen: ' + diagEl('recording-export-filename').value;
    mode = '';
    diagEl('recording-export-dialog').close();
    render();
  });
  diagEl('recording-export-dialog').addEventListener('close', () => { pendingExport = null; });
  diagEl('recording-check-result').addEventListener('change', renderPackage);
  diagEl('diagnostics-close').addEventListener('click', close);
  diagEl('diagnostics-return').addEventListener('click', close);
  diagEl('diagnostics-preview').addEventListener('change', event => applyPreview(event.target.value));
  diagEl('diagnostics-logging-preview').checked = ReferenceDesign.readSession('logging-enabled', false);
  diagEl('diagnostics-logging-preview').addEventListener('change', event => { ReferenceDesign.writeSession('logging-enabled', event.target.checked); render(); });
  for (const link of document.querySelectorAll('[data-recording-demo-link]')) link.href = ReferenceDesign.pageUrl(link.dataset.recordingDemoLink, { recording: 'demo' });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || diagEl('recording-export-dialog').open || event.target.closest('.reference-tools, .reference-switcher, select')) return;
    close();
  });
  let wasActive = Boolean(ReferenceRecording.state().active);
  window.setInterval(() => {
    const active = Boolean(ReferenceRecording.state().active);
    if (wasActive && !active) {
      selectedId = ReferenceRecording.state().items[0]?.id;
      selectTab('history');
      status = 'Snimanje je završeno. Razlog završetka naveden je uz snimak.';
    }
    wasActive = active;
    render();
  }, 1000);
  const view = query.get('view');
  if ([...diagEl('diagnostics-preview').options].some(option => option.value === view)) {
    diagEl('diagnostics-preview').value = view;
    applyPreview(view);
  } else render();
})();
