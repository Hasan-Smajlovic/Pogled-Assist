(() => {
  'use strict';

  const checkEl = id => document.getElementById(id);
  let checkMode = 'position';
  let checkTrialIndex = 0;
  const noGazeExample = new URLSearchParams(location.search).get('trial') === 'no-gaze';
  let checkTrialFinished = false;
  // Synthetic examples only; measurement rules belong to docs/ARCHITECTURE.md.
  let checkDetails = false;
  const checkNames = ['Sredina', 'Gore lijevo', 'Gore desno', 'Dolje lijevo', 'Dolje desno'];
  function checkPolicyLabel() {
    return 'Režim: ' + ReferenceEyePolicy.label()
      + (ReferenceEyePolicy.read() === 'hold' ? ' · prekid do ' + ReferenceEyePolicy.holdMs() + ' ms' : '');
  }
  function renderCheckTracking() {
    const state = checkEl('check-tracking-preview').value;
    const eyes = { both: [true, true], left: [true, false], right: [false, true], held: [true, false], 'no-gaze': [true, false], none: [false, false] }[state];
    const usable = ReferenceEyePolicy.usable(eyes, !['no-gaze', 'none'].includes(state));
    const held = state === 'held' && ReferenceEyePolicy.read() === 'hold';
    for (const [id, label, valid] of [['check-left-eye', 'Lijevo', eyes[0]], ['check-right-eye', 'Desno', eyes[1]]]) {
      checkEl(id).textContent = (valid ? '✓ ' : '— ') + label + ' oko · ' + (valid ? 'prepoznato' : 'trenutno se ne prati');
      checkEl(id).className = 'check-line ' + (valid ? 'check-pass' : 'check-attention');
    }
    checkEl('check-gaze-state').textContent = usable ? '✓ Pogled je dostupan u ovom režimu' : '— Čekam pogled dopušten u ovom režimu';
    checkEl('check-gaze-state').className = 'check-line ' + (usable ? 'check-pass' : 'check-attention');
    const stableExample = state === 'both' || state === 'held';
    checkEl('check-both-continuity').textContent = stableExample ? '✓ Oba oka · praćenje je uglavnom neprekinuto' : '— Oba oka · praćenje ima prekide';
    checkEl('check-both-continuity').className = 'check-line ' + (stableExample ? 'check-pass' : 'check-attention');
    checkEl('check-both-continuity').title = 'Izmišljeni primjer kontinuiteta oba oka kroz vrijeme; ovo nije ocjena izabranog režima niti mjerenje preciznosti.';
    for (const id of ['check-policy-summary', 'check-test-policy', 'check-result-policy']) checkEl(id).textContent = checkPolicyLabel();
    checkEl('check-gaze').hidden = checkMode !== 'free' || !usable;
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
  function checkResultTable() {
    const missingTrialGaze = noGazeExample && checkTrialFinished;
    const statuses = missingTrialGaze ? Array(5).fill('✓ Pogled blizu mete') : [
      '✓ Pogled blizu mete', '✓ Pogled blizu mete', '! Pogled izvan mete',
      '✓ Pogled blizu mete', '— Premalo podataka',
    ];
    const values = missingTrialGaze ? Array(5).fill(['90%', '12 px', '8 px']) : [
      ['90%', '12 px', '8 px'], ['90%', '14 px', '10 px'], ['90%', '48 px', '12 px'],
      ['90%', '18 px', '9 px'], ['20%', '—', '—'],
    ];
    const headings = checkDetails ? ['Meta', 'Podaci', 'Odstupanje', 'Rasipanje'] : ['Meta', 'Rezultat'];
    const rows = checkNames.map((name, index) => {
      let tone = 'check-pass';
      if (!missingTrialGaze && index === 4) tone = 'muted';
      else if (!missingTrialGaze && index === 2) tone = 'check-attention';
      const cells = checkDetails
        ? values[index].map(value => `<td>${value}</td>`).join('')
        : `<td class="${tone}">${statuses[index]}</td>`;
      return `<tr><td>${name}</td>${cells}</tr>`;
    });
    checkEl('check-result-table').innerHTML = '<tr>'
      + headings.map(heading => `<th>${heading}</th>`).join('') + '</tr>' + rows.join('');
    checkEl('check-details').textContent = checkDetails ? 'Sakrij mjerenja' : 'Prikaži mjerenja';
    checkEl('check-metrics-help').hidden = !checkDetails;
    checkEl('check-result-title').textContent = missingTrialGaze
      ? '✓ Pogled je bio blizu 5 od 5 meta.' : '— Za 1 od 5 meta nema dovoljno podataka.';
    const requirement = ReferenceEyePolicy.read() === 'any' ? 'najmanje jedno oko i svjež pogled' : 'oba oka i svjež pogled';
    checkEl('check-result-advice').textContent = missingTrialGaze
      ? 'Tokom dijela probe nije bilo dovoljno podataka o pogledu. Podesite položaj: potrebni su ' + requirement + ', pa ponovite probu.'
      : 'Odaberite „Podesi položaj“. Za novi test potrebni su ' + requirement + '.';
    if (missingTrialGaze) {
      checkEl('check-trial-result').textContent = '! Probni izbor: 0/3 · pogrešni izbori: 0 · poništeni izbori: 0';
    }
    checkEl('check-results').querySelector('.check-map i').hidden = missingTrialGaze;
  }
  function checkReset() {
    checkMode = 'position';
    checkDetails = false;
    checkTrialFinished = false;
    checkResultTable();
    checkEl('check-live').hidden = false;
    checkEl('check-test').hidden = true;
    checkEl('check-results').hidden = true;
    checkEl('check-trial-result').hidden = true;
    checkEl('check-step').textContent = '1 · Položaj i praćenje';
    checkEl('check-notice').textContent = 'Upravljanje pogledom je pauzirano tokom provjere.';
    checkEl('check-next').textContent = 'Provjeri preciznost';
    checkEl('check-reset').hidden = true;
    renderCheckTracking();
  }

  function checkStage(mode) {
    if (checkMode !== mode) checkTrialIndex = 0;
    checkMode = mode;
    checkEl('check-test').classList.toggle('free', mode === 'free');
    checkEl('check-live').hidden = true;
    checkEl('check-results').hidden = true;
    checkEl('check-test').hidden = false;
    checkEl('check-gaze').hidden = mode !== 'free';
    checkEl('check-test-next').hidden = mode === 'free';
    const targets = checkEl('check-targets');
    targets.replaceChildren();
    if (mode === 'trial') {
      const [width, height, gap, left, top] = [
        [136, 64, 12, 64, 14],
        [96, 88, 10, 64, window.innerHeight - 270],
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
          const progress = document.createElement('i');
          progress.className = 'check-trial-progress';
          button.append(progress);
        }
        targets.append(button);
      }
      checkEl('check-test-next').textContent = checkTrialIndex < 2
        ? 'Sljedeća probna grupa' : 'Prikaži primjer rezultata';
    } else {
      checkEl('check-test-next').textContent = 'Prikaži primjer rezultata';
      const rows = mode === 'free' ? [.06, .5, .94] : [.5];
      const columns = mode === 'free' ? [.04, .5, .96] : [.5];
      for (const y of rows) {
        for (const x of columns) {
          const dot = document.createElement('span');
          dot.className = 'check-target';
          dot.style.left = `calc(${x * 100}% - 36px)`;
          dot.style.top = `calc(${y * 100}% - 36px)`;
          dot.textContent = '+';
          targets.append(dot);
        }
      }
    }
    checkEl('check-progress').hidden = mode !== 'precision';
    checkEl('check-test-copy').innerHTML = mode === 'free'
      ? 'Gledajte križiće redom. Zelena oznaka pokazuje vaš pogled.'
      : mode === 'trial'
        ? `Dugme ${checkTrialIndex + 1} od 3 · Gledajte „Pogledaj“.<br>`
          + '<span class="muted">Zadržite pogled dok se traka ne popuni.</span>'
        : 'Meta 1 od 5 · Gledajte križić u krugu.<br>'
          + '<span class="muted">Meta se mijenja sama; ne trebate kliknuti.</span>';
    renderCheckTracking();
  }
  checkEl('check-next').addEventListener('click', () => {
    checkStage(checkMode === 'results' ? 'trial' : 'precision');
  });
  checkEl('check-free').addEventListener('click', () => checkStage('free'));
  checkEl('check-test-next').addEventListener('click', () => {
    if (checkMode === 'trial' && checkTrialIndex < 2) {
      checkTrialIndex++;
      checkStage('trial');
      return;
    }
    if (checkMode === 'trial') {
      checkTrialFinished = true;
      checkEl('check-trial-result').hidden = false;
      checkEl('check-trial-result').textContent = '! Probni izbor: 3/3 · pogrešni izbori: 1';
      checkEl('check-next').textContent = 'Ponovi probu dugmadi';
    } else {
      checkEl('check-next').textContent = 'Probaj izbor dugmeta';
    }
    checkMode = 'results';
    checkEl('check-step').textContent = 'Rezultat provjere';
    checkEl('check-test').hidden = true;
    checkEl('check-results').hidden = false;
    checkEl('check-reset').textContent = 'Podesi položaj';
    checkEl('check-reset').hidden = false;
    checkResultTable();
    renderCheckTracking();
  });
  checkEl('check-details').addEventListener('click', () => {
    checkDetails = !checkDetails;
    checkResultTable();
  });
  checkEl('check-test-back').addEventListener('click', checkReset);
  checkEl('check-reset').addEventListener('click', checkReset);
  checkEl('check-calibrate').addEventListener('click', () => {
    checkReset();
    checkEl('check-notice').textContent = 'U Tobii Core odaberite profil korisnika > '
      + 'Test and recalibrate > Recalibrate. Vratite se ovdje i ponovite provjeru.';
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || event.target.closest('.reference-switcher')) return;
    if (!checkEl('check-test').hidden) checkReset();
    else ReferenceDesign.returnTo();
  });
  ReferenceEyePolicy.setupSelect(checkEl('check-policy-preview'), checkReset);
  checkEl('check-tracking-preview').addEventListener('change', renderCheckTracking);
  checkReset();
})();
