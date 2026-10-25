(() => {
  'use strict';

  const checkEl = id => document.getElementById(id);
  const query = new URLSearchParams(location.search);
  const noGazeExample = query.get('trial') === 'no-gaze';
  const names = ['Sredina', 'Gore lijevo', 'Gore desno', 'Dolje lijevo', 'Dolje desno'];
  const positions = [[.5, .5], [.04, .06], [.96, .06], [.04, .94], [.96, .94]];
  const policyNames = { both: 'Oba oka', hold: 'Oba oka uz kratke prekide', any: 'Jedno oko je dovoljno (probno)' };
  const tabs = ['precision', 'trial', 'context'];
  let checkMode = 'position';
  let checkTrialIndex = 0;
  let checkDetails = false;
  let reportTab = 'precision';
  let currentReport = null;
  let displayedReport = null;
  let viewingArchive = false;
  let historyItems = [];
  let selectedHistoryId = null;
  let attemptSequence = 0;
  let activeAttemptId = null;
  let returnMode = 'position';

  function policyLabel(policy = ReferenceEyePolicy.read(), holdMs = ReferenceEyePolicy.holdMs()) {
    return policyNames[policy] + (policy === 'hold' ? ' · prekid do ' + holdMs + ' ms' : '');
  }

  function makeReport(id, date, policy = ReferenceEyePolicy.read(), interrupted = false) {
    const report = {
      id, date, policy, holdMs: ReferenceEyePolicy.holdMs(), pauseMs: 250, dwellMs: 850, edgeMs: 120, cooldownMs: 350,
      duration: interrupted ? '7 s' : '15 s',
      storage: 'saved', state: interrupted ? 'interrupted' : 'completed',
      reason: interrupted ? 'Provjera je prekinuta tokom treće mete.' : '',
      results: names.map((name, index) => samplePrecisionRow(name, index, interrupted)),
      trials: [],
    };
    if (noGazeExample && !interrupted) report.results.forEach((row, index) => {
      Object.assign(row, { state: 'measured', near: true, coverage: 90, samples: 108, error: 12, spread: 8, center: positions[index] });
    });
    return report;
  }

  function samplePrecisionRow(name, index, interrupted) {
    if (interrupted && index >= 2) return { name, state: 'unmeasured' };
    return {
      name, coverage: [90, 90, 90, 90, 20][index], samples: [108, 108, 108, 108, 8][index],
      error: [12, 14, 48, 18, null][index], spread: [8, 10, 12, 9, null][index],
      state: index === 4 ? 'insufficient' : 'measured',
      near: index !== 2, center: [[.509, .504], [.05, .069], [.925, .095], [.052, .93], null][index],
    };
  }

  function makeTrial(id, interrupted = false) {
    return {
      id, date: '22.10.2026. · 14:33', state: interrupted ? 'interrupted' : 'completed',
      duration: interrupted ? '4,2 s' : '8,6 s',
      reason: interrupted ? 'Prekinuto: proba je zaustavljena tokom druge grupe.' : '',
      rows: [0, 1, 2].map(index => sampleTrialRow(index, interrupted)),
    };
  }

  function sampleTrialRow(index, interrupted) {
    let state = noGazeExample ? 'insufficient' : 'measured';
    if (interrupted && index > 0) state = 'unmeasured';
    return {
      size: ['136 × 64', '96 × 88', '180 × 72'][index], state,
      coverage: noGazeExample ? [0, 12, 20][index] : [92, 85, 90][index],
      correct: !noGazeExample, wrong: Number(!noGazeExample && index === 1),
      losses: Number(!noGazeExample && index === 0), departures: !noGazeExample ? index + 1 : 0,
    };
  }

  function rememberReport(report) {
    if (!historyItems.some(item => item.id === report.id)) historyItems.unshift(report);
  }

  function setTab(name, focus = false) {
    reportTab = name;
    for (const tab of tabs) {
      const selected = tab === name;
      const button = checkEl('check-tab-' + tab);
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
      checkEl('check-panel-' + tab).hidden = !selected;
      if (selected && focus) button.focus();
    }
  }

  function renderFrame() {
    const results = checkMode === 'results';
    const history = checkMode === 'history';
    const position = checkMode === 'position';
    const stage = ['precision', 'trial', 'free'].includes(checkMode);
    checkEl('check-live').hidden = !position;
    checkEl('check-results').hidden = !results;
    checkEl('check-history-view').hidden = !history;
    checkEl('check-test').hidden = !stage;
    renderCheckHeading(results, history);
    renderCheckActions(results, history, position);
  }
  function renderCheckHeading(results, history) {
    checkEl('check-heading').textContent = history ? 'Sačuvani rezultati' : viewingArchive ? 'Raniji rezultat provjere' : 'Provjera pogleda';
    document.querySelector('.check-simulation').hidden = history;
    checkEl('check-policy-summary').textContent = history ? 'Rezultati ovog uređaja · najnoviji su prvi'
      : 'Režim: ' + (results ? policyLabel(displayedReport.policy, displayedReport.holdMs) : policyLabel());
  }
  function renderCheckActions(results, history, position) {
    checkEl('check-history').hidden = history || viewingArchive;
    checkEl('check-step').hidden = !position;
    checkEl('check-calibrate').hidden = !position;
    checkEl('check-device-actions').hidden = !position;
    checkEl('check-free').hidden = !position;
    checkEl('check-next').hidden = history || viewingArchive;
    checkEl('check-next').textContent = nextCheckLabel(results);
    checkEl('check-next').disabled = results && displayedReport.state === 'interrupted';
    const repeatPrecision = results && (displayedReport.state === 'interrupted'
      || displayedReport.results.some(row => row.state !== 'measured' || !row.near));
    checkEl('check-next').classList.toggle('primary', !results || !repeatPrecision);
    checkEl('check-repeat').classList.toggle('primary', repeatPrecision);
    checkEl('check-reset').hidden = !results || viewingArchive;
    checkEl('check-repeat').hidden = !results || viewingArchive;
    checkEl('check-back').hidden = !history && !viewingArchive;
    checkEl('check-back').textContent = viewingArchive ? 'Nazad na listu' : 'Nazad na provjeru';
    checkEl('check-open-result').hidden = !history;
    checkEl('check-notice').textContent = 'Upravljanje pogledom pauzirano · Koristite miš ili tastaturu.';
  }

  function nextCheckLabel(results) {
    if (!results) return 'Provjeri preciznost';
    return displayedReport.trials.length ? 'Ponovi probu dugmadi' : 'Probaj izbor dugmeta';
  }

  function renderCheckTracking() {
    const state = checkEl('check-tracking-preview').value;
    const eyes = { both: [true, true], left: [true, false], right: [false, true], held: [true, false], 'no-gaze': [true, false], none: [false, false] }[state];
    const usable = ReferenceEyePolicy.usable(eyes, !['no-gaze', 'none'].includes(state));
    const held = state === 'held' && ReferenceEyePolicy.read() === 'hold';
    renderCheckEyes(eyes);
    checkEl('check-gaze-state').textContent = usable ? '✓ Pogled je dostupan u ovom režimu' : '— Čekam pogled dopušten u ovom režimu';
    checkEl('check-gaze-state').className = 'check-line ' + (usable ? 'check-pass' : 'check-attention');
    const stableExample = state === 'both' || state === 'held';
    checkEl('check-both-continuity').textContent = stableExample ? '✓ Oba oka · praćenje je uglavnom neprekinuto' : '— Oba oka · praćenje ima prekide';
    checkEl('check-both-continuity').className = 'check-line ' + (stableExample ? 'check-pass' : 'check-attention');
    checkEl('check-both-continuity').title = 'Izmišljeni primjer kontinuiteta oba oka kroz vrijeme; ovo nije ocjena izabranog režima niti mjerenje preciznosti.';
    checkEl('check-test-policy').textContent = 'Režim: ' + policyLabel();
    checkEl('check-gaze').hidden = checkMode !== 'free' || !usable;
    renderTrialTracking(usable, held);
  }
  function renderCheckEyes(eyes) {
    for (const [id, label, valid] of [['check-left-eye', 'Lijevo', eyes[0]], ['check-right-eye', 'Desno', eyes[1]]]) {
      checkEl(id).textContent = (valid ? '✓ ' : '— ') + label + ' oko · ' + (valid ? 'prepoznato' : 'trenutno se ne prati');
      checkEl(id).className = 'check-line ' + (valid ? 'check-pass' : 'check-attention');
    }
  }
  function renderTrialTracking(usable, held) {
    for (const bar of document.querySelectorAll('.check-trial-progress')) {
      bar.hidden = !usable && !held;
      bar.classList.toggle('held', held);
      bar.parentElement.querySelector('.check-trial-hold')?.remove();
      if (held) {
        const pause = document.createElement('small');
        pause.className = 'check-trial-hold'; pause.textContent = 'Ⅱ Na čekanju';
        bar.parentElement.append(pause);
      }
    }
    if (checkMode === 'trial') checkEl('check-test-copy').textContent = held
      ? 'Ⅱ Napredak je na čekanju. Rok: ' + ReferenceEyePolicy.holdMs() + ' ms.'
      : !usable ? 'Nema odabira bez dopuštenog svježeg pogleda.'
        : 'Dugme ' + (checkTrialIndex + 1) + ' od 3 · Gledajte „Pogledaj“.';
  }

  function renderPrecision() {
    const report = displayedReport;
    const summary = [
      ['Blizu mete', report.results.filter(row => row.state === 'measured' && row.near).length, 'check-pass'],
      ['Izvan mete', report.results.filter(row => row.state === 'measured' && !row.near).length, 'check-attention'],
      ['Premalo podataka', report.results.filter(row => row.state === 'insufficient').length, ''],
      ['Nije izmjereno', report.results.filter(row => row.state === 'unmeasured').length, ''],
    ];
    checkEl('check-result-summary').innerHTML = summary.map(([label, count, tone]) =>
      `<div><strong class="${count ? tone : ''}">${count}</strong><span>${label}</span></div>`).join('');
    const headings = checkDetails ? ['Meta', 'Uzorci', 'Podaci', 'Odstupanje', 'Rasipanje'] : ['Meta', 'Rezultat'];
    const rows = report.results.map(precisionRow);
    checkEl('check-result-table').innerHTML = '<thead><tr>' + headings.map(heading => `<th scope="col">${heading}</th>`).join('') + '</tr></thead><tbody>' + rows.join('') + '</tbody>';
    checkEl('check-result-table').classList.toggle('check-metrics-details', checkDetails);
    checkEl('check-details').textContent = checkDetails ? 'Sakrij mjerenja' : 'Prikaži mjerenja';
    checkEl('check-details').setAttribute('aria-pressed', String(checkDetails));
    checkEl('check-metrics-help').hidden = !checkDetails;
    checkEl('check-result-advice').textContent = precisionAdvice(report);
    renderPrecisionMap(report);
  }
  function precisionRow(result) {
    const tone = result.state !== 'measured' ? 'muted' : result.near ? 'check-pass' : 'check-attention';
    const values = precisionValues(result);
    const cells = checkDetails ? values.map(value => `<td>${value}</td>`).join('') : `<td class="${tone}">${precisionStatus(result)}</td>`;
    return `<tr><th scope="row">${result.name}</th>` + cells + '</tr>';
  }
  function precisionStatus(result) {
    if (result.state === 'unmeasured') return '— Nije izmjereno';
    if (result.state === 'insufficient') return '— Premalo podataka';
    return result.near ? '✓ Pogled blizu mete' : '! Pogled izvan mete';
  }
  function precisionValues(result) {
    if (result.state === 'unmeasured') return ['—', '—', '—', '—'];
    return [result.samples, result.coverage + '%', result.error === null ? '—' : result.error + ' px', result.spread === null ? '—' : result.spread + ' px'];
  }
  function precisionAdvice(report) {
    const count = state => report.results.filter(result => result.state === state).length;
    return report.state === 'interrupted'
      ? 'Sačuvane su završene mete. Za cijeli test odaberite „Ponovi preciznost“.'
      : count('insufficient') || count('unmeasured') ? 'Za neke mete nema dovoljno podataka. Podesite položaj pa ponovite provjeru.'
        : report.results.some(result => result.state === 'measured' && !result.near)
          ? 'Pogled je na nekim metama izvan kruga. Podesite položaj pa ponovite provjeru.'
          : 'Pogled je blizu svih meta. Možete probati izbor dugmeta.';
  }
  function renderPrecisionMap(report) {
    const map = checkEl('check-result-map');
    map.replaceChildren();
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 100 100'); svg.setAttribute('preserveAspectRatio', 'none'); svg.setAttribute('aria-hidden', 'true');
    map.append(svg);
    report.results.forEach((result, index) => {
      const [x, y] = positions[index];
      const target = document.createElement('span');
      target.style.left = x * 100 + '%'; target.style.top = y * 100 + '%';
      target.title = result.name + (result.state === 'unmeasured' ? ' · nije izmjereno' : '');
      map.append(target);
      if (result.state !== 'measured') return;
      const [gx, gy] = result.center;
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      for (const [attr, value] of Object.entries({ x1: x * 100, y1: y * 100, x2: gx * 100, y2: gy * 100 })) line.setAttribute(attr, value);
      svg.append(line);
      const dot = document.createElement('i');
      dot.style.left = gx * 100 + '%'; dot.style.top = gy * 100 + '%';
      map.append(dot);
    });
  }

  function renderTrial() {
    const trial = displayedReport.trials[Number(checkEl('check-trial-attempt').value)];
    if (!trial) return;
    const measured = trial.rows.filter(row => row.state === 'measured');
    checkEl('check-trial-result').textContent = (trial.state === 'interrupted' ? trial.reason + ' ' : '')
      + 'Izmjerene grupe: ' + measured.length + '/3 · Tačni izbori: ' + measured.filter(row => row.correct).length
      + ' · Pogrešni: ' + measured.reduce((sum, row) => sum + row.wrong, 0)
      + ' · Poništeni: ' + measured.reduce((sum, row) => sum + row.losses, 0) + ' · Trajanje: ' + trial.duration;
    checkEl('check-trial-table').innerHTML = '<thead><tr><th>Grupa · veličina (px)</th><th>Rezultat</th><th>Podaci</th><th>Pogrešni</th><th>Poništeni</th><th>Izlasci</th></tr></thead><tbody>'
      + trial.rows.map((row, index) => {
        const measured = row.state === 'measured';
        const status = row.state === 'unmeasured' ? '— Nije izmjereno' : row.state === 'insufficient' ? '— Premalo podataka' : '✓ Tačan izbor';
        return `<tr><th scope="row">${index + 1} · ${row.size}</th><td class="${measured ? 'check-pass' : 'muted'}">${status}</td><td>${row.state === 'unmeasured' ? '—' : row.coverage + '%'}</td>`
          + [row.wrong, row.losses, row.departures].map(value => `<td>${row.state === 'unmeasured' ? '—' : value}</td>`).join('') + '</tr>';
      }).join('') + '</tbody>';
  }

  function renderStorage() {
    const storage = displayedReport.storage;
    const states = {
      saved: ['✓ Sačuvano na ovom uređaju', 'Dostupno u „Sačuvanim rezultatima“ i nakon zatvaranja aplikacije.'],
      off: ['— Samo u memoriji · zapisivanje je isključeno', 'Izvezite ZIP prije zatvaranja aplikacije ako želite zadržati rezultat.'],
      saving: ['Čuvanje rezultata…', 'Rezultat je dostupan za pregled i ručni izvoz.'],
      error: ['! Rezultat nije sačuvan na disk', 'Čuvanje nije uspjelo. Rezultat je u memoriji; pokušajte ponovo ili izvezite ZIP.'],
    };
    checkEl('check-save-status').textContent = states[storage][0];
    checkEl('check-save-status').className = storage === 'error' ? 'check-attention' : storage === 'saved' ? 'check-pass' : '';
    checkEl('check-save-help').textContent = states[storage][1];
    checkEl('check-save-retry').hidden = storage !== 'error';
  }

  function showReport(report, archived = false) {
    displayedReport = report;
    viewingArchive = archived;
    checkMode = 'results';
    checkEl('check-result-title').textContent = report.state === 'interrupted' ? 'Provjera preciznosti · Prekinuto' : 'Provjera preciznosti · Završeno';
    checkEl('check-result-meta').textContent = report.date + ' · Trajanje: ' + report.duration + ' · ID: ' + report.id;
    renderPrecision();
    checkEl('check-trial-empty').hidden = report.trials.length > 0;
    checkEl('check-trial-data').hidden = report.trials.length === 0;
    checkEl('check-trial-attempt').replaceChildren(...report.trials.map((trial, index) => new Option(
      'Pokušaj ' + (index + 1) + ' · ' + trial.date + ' · ' + (trial.state === 'interrupted' ? 'Prekinuto' : 'Završeno') + ' · ' + trial.id, index)));
    checkEl('check-trial-attempt').value = String(report.trials.length - 1);
    renderTrial();
    checkEl('check-used-settings').innerHTML = [
      ['Režim praćenja očiju', policyLabel(report.policy, report.holdMs)],
      ['Čuvanje pri gubitku oka', report.holdMs + ' ms' + (report.policy !== 'hold' ? ' · nije aktivno' : '')],
      ['Pauza prije odabira', report.pauseMs + ' ms'], ['Vrijeme zadržavanja', report.dwellMs + ' ms'],
      ['Čuvanje uz rub', report.edgeMs + ' ms'], ['Pauza između radnji', report.cooldownMs + ' ms'],
    ].map(([label, value]) => `<dt>${label}</dt><dd>${value}</dd>`).join('');
    checkEl('check-environment').innerHTML = [
      ['Izvor podataka', 'Simulacija mišem · izmišljeni podaci'], ['Verzija / revizija aplikacije', 'Nije dostupno u ovom primjeru'],
      ['Lokalne izmjene izvora', 'Nije dostupno u ovom primjeru'],
      ['Tobii model / SDK', 'Nije dostupno u simulaciji'], ['Sistem', 'Windows 11 · primjer'],
      ['Ekran / skaliranje', '1920 × 1080 fizičkih px · 150%'], ['Prikaz aplikacije', '1280 × 720 logičkih px'],
    ].map(([label, value]) => `<dt>${label}</dt><dd>${value}</dd>`).join('');
    checkEl('check-export-status').hidden = true;
    renderStorage();
    setTab(reportTab);
    renderFrame();
  }

  function trialSummary(report) {
    const latest = report.trials.at(-1);
    return latest ? report.trials.length + ' · posljednji pokušaj ' + (latest.state === 'interrupted' ? 'prekinut' : 'završen') : 'Nisu pokrenute';
  }

  function renderHistorySelection() {
    const selected = historyItems.find(item => item.id === selectedHistoryId);
    for (const button of checkEl('check-history-list').querySelectorAll('button')) button.setAttribute('aria-pressed', String(button.dataset.reportId === selectedHistoryId));
    checkEl('check-open-result').disabled = !selected || selected.unreadable;
    const preview = checkEl('check-history-preview');
    preview.replaceChildren();
    if (!selected) return;
    if (selected.unreadable) {
      preview.innerHTML = '<h2>! Rezultat se ne može otvoriti</h2><p>Datoteka je oštećena ili je zapisana u nepodržanoj verziji formata.</p><p class="muted">Izvorna datoteka ostaje sačuvana. Odaberite drugi rezultat.</p>';
      return;
    }
    preview.innerHTML = '<h2>' + selected.date + '</h2><span class="check-badge">Simulacija</span><dl>'
      + [['Režim', policyLabel(selected.policy, selected.holdMs)], ['Preciznost', selected.state === 'interrupted' ? 'Prekinuto' : 'Završeno'],
        ['Obrađene mete', selected.results.filter(row => row.state !== 'unmeasured').length + ' od 5'],
        ['Probe dugmadi', trialSummary(selected)],
        ['Čuvanje', selected.storage === 'saved' ? 'Na ovom uređaju' : selected.storage === 'saving' ? 'U toku · zasad u memoriji' : 'Samo u memoriji'],
        ['Identifikator', selected.id]].map(([label, value]) => `<dt>${label}</dt><dd>${value}</dd>`).join('')
      + '</dl><p class="muted">Otvorite rezultat za mjerenja, korištene postavke i izvoz ZIP-a.</p>';
  }

  function showHistory() {
    if (checkMode !== 'history' && !viewingArchive) returnMode = checkMode;
    viewingArchive = false;
    checkMode = 'history';
    const list = checkEl('check-history-list');
    list.replaceChildren();
    for (const report of historyItems) {
      list.append(historyButton(report));
    }
    if (!historyItems.some(item => item.id === selectedHistoryId)) selectedHistoryId = historyItems[0]?.id;
    checkEl('check-history-content').hidden = historyItems.length === 0;
    checkEl('check-history-empty').hidden = historyItems.length !== 0;
    renderHistorySelection();
    renderFrame();
  }

  function historyButton(report) {
    const button = document.createElement('button');
    button.dataset.reportId = report.id;
    const title = document.createElement('strong'); title.textContent = report.date;
    const detail = document.createElement('small');
    detail.textContent = report.unreadable ? '! Nečitljiv rezultat' : policyNames[report.policy] + ' · Preciznost: ' + (report.state === 'interrupted' ? 'Prekinuto' : 'Završeno');
    const saved = document.createElement('small');
    saved.textContent = report.unreadable ? 'Datoteka je zadržana' : report.storage === 'saved' ? 'Sačuvano na uređaju · Simulacija' : 'Samo u memoriji · Simulacija';
    button.append(title, detail, saved);
    if (report.trials?.length) { const trial = document.createElement('small'); trial.textContent = 'Probe: ' + trialSummary(report); button.append(trial); }
    button.addEventListener('click', () => { selectedHistoryId = report.id; renderHistorySelection(); });
    return button;
  }

  function checkReset() {
    checkMode = 'position';
    viewingArchive = false;
    checkDetails = false;
    reportTab = 'precision';
    activeAttemptId = null;
    renderFrame();
    renderCheckTracking();
  }

  function checkStage(mode) {
    if (checkMode !== mode) {
      checkTrialIndex = 0;
      activeAttemptId = 'pokusaj-' + (++attemptSequence);
    }
    checkMode = mode;
    viewingArchive = false;
    renderFrame();
    checkEl('check-test').classList.toggle('free', mode === 'free');
    checkEl('check-test-next').hidden = mode === 'free';
    checkEl('check-test-back').textContent = mode === 'free' ? 'Nazad na položaj' : 'Prekini i prikaži rezultat';
    const targets = checkEl('check-targets');
    targets.replaceChildren();
    if (mode === 'trial') {
      renderTrialTargets(targets);
    } else {
      renderFreeTargets(targets, mode);
    }
    checkEl('check-progress').hidden = mode !== 'precision';
    checkEl('check-test-copy').innerHTML = mode === 'free' ? 'Gledajte križiće redom. Zelena oznaka pokazuje vaš pogled.'
      : mode === 'trial' ? 'Gledajte „Pogledaj“. Zadržite pogled dok se traka ne popuni.'
        : 'Meta 1 od 5 · Gledajte križić u krugu.<br><span class="muted">Meta se mijenja sama; ne trebate kliknuti.</span>';
    renderCheckTracking();
  }

  function renderTrialTargets(targets) {
    const [width, height, gap, left, top] = [
      [136, 64, 12, 64, 14],
      [96, 88, 10, 64, window.innerHeight - 290],
      [180, 72, 12, Math.floor(window.innerWidth / 2) - 282, Math.floor(window.innerHeight / 2) - 36],
    ][checkTrialIndex];
    const expected = [1, 0, 2][checkTrialIndex];
    for (let i = 0; i < 3; i++) {
      const button = document.createElement('span');
      button.className = 'check-target';
      button.style.cssText = `left:${left + i * (width + gap)}px;top:${top}px;`
        + `width:${width}px;height:${height}px;border-radius:10px;font-size:24px;`
        + `border-color:${i === expected ? '#8bd5f5' : '#58647a'}`;
      button.textContent = i === expected ? 'Pogledaj' : 'Drugo';
      if (i === expected) {
        const progress = document.createElement('i'); progress.className = 'check-trial-progress'; button.append(progress);
      }
      targets.append(button);
    }
    checkEl('check-test-next').textContent = checkTrialIndex < 2 ? 'Sljedeća probna grupa' : 'Prikaži primjer rezultata';
  }
  function renderFreeTargets(targets, mode) {
    checkEl('check-test-next').textContent = 'Prikaži primjer rezultata';
    const rows = mode === 'free' ? [.06, .5, .94] : [.5];
    const columns = mode === 'free' ? [.04, .5, .96] : [.5];
    for (const y of rows) for (const x of columns) {
      const dot = document.createElement('span'); dot.className = 'check-target';
      dot.style.left = `calc(${x * 100}% - 36px)`; dot.style.top = `calc(${y * 100}% - 36px)`; dot.textContent = '+';
      targets.append(dot);
    }
  }

  function finishAttempt(interrupted = false) {
    if (checkMode === 'free') { checkReset(); return; }
    if (checkMode === 'precision') {
      currentReport = makeReport(activeAttemptId, '22.10.2026. · 14:32', ReferenceEyePolicy.read(), interrupted);
      currentReport.storage = storageForPreview();
    } else if (checkMode === 'trial') currentReport.trials.push(makeTrial(activeAttemptId, interrupted));
    rememberReport(currentReport);
    reportTab = checkMode === 'trial' ? 'trial' : 'precision';
    showReport(currentReport);
  }

  function storageForPreview() {
    return { 'logging-off': 'off', 'save-error': 'error', saving: 'saving' }[checkEl('check-view-preview').value] || 'saved';
  }

  function loadPreview(view) {
    checkEl('check-view-preview').value = view;
    checkReset();
    currentReport = null;
    displayedReport = null;
    selectedHistoryId = null;
    returnMode = 'position';
    historyItems = [makeReport('provjera-014', '21.10.2026. · 17:45', 'hold'), makeReport('provjera-013', '21.10.2026. · 17:38', 'any', true)];
    if (view === 'empty') historyItems = [];
    else if (view !== 'position') {
      currentReport = previewReport(view);
      rememberReport(currentReport);
    }
    if (view === 'history-error') historyItems.unshift({ id: 'provjera-016', date: '22.10.2026. · 14:40', unreadable: true });
    if (['history', 'empty', 'history-error'].includes(view)) showHistory();
    else if (currentReport) { reportTab = view.startsWith('trial') ? 'trial' : 'precision'; showReport(currentReport); }
  }

  function previewReport(view) {
    const report = makeReport('provjera-015', '22.10.2026. · 14:32', ReferenceEyePolicy.read(), view === 'interrupted');
    report.storage = storageForPreview();
    if (['trial', 'trial-interrupted'].includes(view) || noGazeExample) report.trials.push(makeTrial('proba-021'));
    if (view === 'trial-interrupted') report.trials.push(makeTrial('proba-022', true));
    return report;
  }

  checkEl('check-next').addEventListener('click', () => checkStage(checkMode === 'results' ? 'trial' : 'precision'));
  checkEl('check-free').addEventListener('click', () => checkStage('free'));
  checkEl('check-repeat').addEventListener('click', () => checkStage('precision'));
  checkEl('check-test-next').addEventListener('click', () => {
    if (checkMode === 'trial' && checkTrialIndex < 2) { checkTrialIndex++; checkStage('trial'); }
    else finishAttempt();
  });
  checkEl('check-test-back').addEventListener('click', () => finishAttempt(true));
  checkEl('check-reset').addEventListener('click', checkReset);
  checkEl('check-calibrate').addEventListener('click', () => {
    checkReset();
    checkEl('check-notice').textContent = 'U Tobii Core odaberite profil korisnika > Test and recalibrate > Recalibrate. Vratite se ovdje i ponovite provjeru.';
  });
  checkEl('check-details').addEventListener('click', () => { checkDetails = !checkDetails; renderPrecision(); });
  for (const tab of tabs) {
    const button = checkEl('check-tab-' + tab);
    button.addEventListener('click', () => setTab(tab));
    button.addEventListener('keydown', event => {
      const index = tabs.indexOf(tab);
      const next = { ArrowRight: (index + 1) % 3, ArrowLeft: (index + 2) % 3, Home: 0, End: 2 }[event.key];
      if (next === undefined) return;
      event.preventDefault(); setTab(tabs[next], true);
    });
  }
  checkEl('check-trial-attempt').addEventListener('change', renderTrial);
  checkEl('check-diagnostics').addEventListener('click', () => {
    ReferenceDesign.writeSession('gaze-check-return', {
      checkMode, checkDetails, reportTab, currentReport, displayedId: displayedReport?.id,
      viewingArchive, historyItems, selectedHistoryId, returnMode, trialIndex: checkEl('check-trial-attempt').value,
    });
    ReferenceDesign.open('diagnostics', { return: 'gaze-check' });
  });
  checkEl('check-history').addEventListener('click', showHistory);
  checkEl('check-open-result').addEventListener('click', () => {
    checkDetails = false; reportTab = 'precision'; showReport(historyItems.find(item => item.id === selectedHistoryId), true);
  });
  checkEl('check-back').addEventListener('click', () => {
    if (viewingArchive) showHistory();
    else if (returnMode === 'results' && currentReport) showReport(currentReport);
    else checkReset();
  });
  checkEl('check-save-retry').addEventListener('click', () => { displayedReport.storage = 'saved'; renderStorage(); });
  checkEl('check-export').addEventListener('click', () => {
    const date = displayedReport.date.slice(0, 10).split('.').reverse().join('-');
    checkEl('check-export-filename').value = 'pogled-provjera-' + date + '-' + displayedReport.id + '.zip';
    checkEl('check-export-dialog').showModal();
  });
  checkEl('check-export-cancel').addEventListener('click', () => checkEl('check-export-dialog').close());
  checkEl('check-export-confirm').addEventListener('click', () => {
    checkEl('check-export-dialog').close();
    const failed = checkEl('check-view-preview').value === 'export-error';
    const status = checkEl('check-export-status');
    status.textContent = failed ? '! Izvoz nije uspio. Rezultat je i dalje dostupan; pokušajte ponovo.' : '✓ ZIP je izvezen: ' + checkEl('check-export-filename').value;
    status.className = 'check-help ' + (failed ? 'check-attention' : 'check-pass');
    status.hidden = false;
  });
  function closeCheck() {
    if (['precision', 'trial'].includes(checkMode)) finishAttempt(true);
    ReferenceDesign.returnTo();
  }
  checkEl('check-close').addEventListener('click', closeCheck);
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || checkEl('check-export-dialog').open || event.target.closest('.reference-switcher, .reference-tools, select')) return;
    closeCheck();
  });
  ReferenceEyePolicy.setupSelect(checkEl('check-policy-preview'), () => loadPreview(checkEl('check-view-preview').value));
  checkEl('check-tracking-preview').addEventListener('change', renderCheckTracking);
  checkEl('check-view-preview').addEventListener('change', event => loadPreview(event.target.value));
  const requestedView = query.get('view') || (noGazeExample ? 'trial' : 'position');
  loadPreview([...checkEl('check-view-preview').options].some(option => option.value === requestedView) ? requestedView : 'position');
  const saved = query.get('resume') === 'diagnostics' ? ReferenceDesign.readSession('gaze-check-return', null) : null;
  if (saved) {
    currentReport = saved.currentReport;
    historyItems = saved.historyItems;
    checkDetails = saved.checkDetails;
    reportTab = saved.reportTab;
    returnMode = saved.returnMode;
    selectedHistoryId = saved.selectedHistoryId;
    checkMode = saved.checkMode;
    if (saved.checkMode === 'history') showHistory();
    else if (saved.checkMode === 'results') showReport(historyItems.find(item => item.id === saved.displayedId) || currentReport, saved.viewingArchive);
    else { renderFrame(); renderCheckTracking(); }
    if (saved.checkMode === 'results' && saved.trialIndex) { checkEl('check-trial-attempt').value = saved.trialIndex; renderTrial(); }
    ReferenceDesign.writeSession('gaze-check-return', null);
  }
})();
