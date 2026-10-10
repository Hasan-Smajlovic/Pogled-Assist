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
    checkEl('check-result-advice').textContent = missingTrialGaze
      ? 'Tokom dijela probe nije bilo dovoljno podataka o pogledu. Podesite položaj dok se prate oba oka, pa ponovite probu.'
      : 'Odaberite „Podesi položaj“. Kad se prate oba oka, ponovite provjeru.';
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
  checkReset();
})();
