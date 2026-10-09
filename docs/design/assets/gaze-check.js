(() => {
  'use strict';

  const checkEl = id => document.getElementById(id);
  let checkMode = 'position';
  let checkTrialIndex = 0;
  // Runtime trial contract: a blink or missing gaze cancels pending progress but
  // never unlocks an already selected neighbor. Only a fresh departure does so.
  // Near-edge hold uses min(24 px, width / 4, height / 4), as in normal controls.
  // Count a direct change to a neighboring button as a departure too, even when
  // no sample lands in the gap. Merely remaining on that neighbor adds nothing.
  // Position guidance precedes the missing-gaze hint when fresh positions are
  // outside the box: align the eyes, move the screen away (both z < 0), or closer
  // (both z > 1). Stale/missing positions must never produce movement directions.
  // If projected eye markers overlap (including clipping to the same edge),
  // show one L/D marker. This visual grouping never changes measured positions.
  // Keep at least 24 px above the position frame so edge markers remain whole.
  let checkDetails = false;
  const checkNames = ['Sredina', 'Gore lijevo', 'Gore desno', 'Dolje lijevo', 'Dolje desno'];
  function checkResultTable() {
  const statuses = ['✓ Pogled blizu mete', '✓ Pogled blizu mete', '! Pogled izvan mete', '✓ Pogled blizu mete', '— Premalo podataka'];
  const values = [['90%', '12 px', '8 px'], ['90%', '14 px', '10 px'], ['90%', '48 px', '12 px'], ['90%', '18 px', '9 px'], ['20%', '—', '—']];
  checkEl('check-result-table').innerHTML = '<tr><th>Meta</th>' + (checkDetails ? '<th>Podaci</th><th>Odstupanje</th><th>Rasipanje</th>' : '<th>Rezultat</th>') + '</tr>' + checkNames.map((name,i) => `<tr><td>${name}</td>${checkDetails ? values[i].map(v=>`<td>${v}</td>`).join('') : `<td class="${i===4?'muted':i===2?'check-attention':'check-pass'}">${statuses[i]}</td>`}</tr>`).join('');
  checkEl('check-details').textContent = checkDetails ? 'Sakrij mjerenja' : 'Prikaži mjerenja';
  checkEl('check-metrics-help').hidden = !checkDetails;
  }
  function checkReset() { checkMode='position'; checkDetails=false; checkResultTable(); checkEl('check-live').hidden=false; checkEl('check-test').hidden=true; checkEl('check-results').hidden=true; checkEl('check-trial-result').hidden=true; checkEl('check-step').textContent='1 · Položaj i praćenje'; checkEl('check-notice').textContent='Upravljanje pogledom je pauzirano tokom provjere.'; checkEl('check-next').textContent='Provjeri preciznost'; checkEl('check-reset').hidden=true; }
  function checkStage(mode) {
  if (checkMode!==mode) checkTrialIndex=0;
  checkMode=mode; checkEl('check-test').classList.toggle('free', mode==='free'); checkEl('check-live').hidden=true; checkEl('check-results').hidden=true; checkEl('check-test').hidden=false; checkEl('check-gaze').hidden=mode!=='free'; checkEl('check-test-next').hidden=mode==='free';
  const targets=checkEl('check-targets'); targets.replaceChildren();
  if (mode==='trial') {
    const [width,height,gap,left,top]=[
  [136,64,12,64,14],
  [96,88,10,64,window.innerHeight-270],
  [180,72,12,Math.floor(window.innerWidth/2)-282,Math.floor(window.innerHeight/2)-36]
    ][checkTrialIndex];
    const expected=[1,0,2][checkTrialIndex];
    for (let i=0;i<3;i++) { const b=document.createElement('span'); b.className='check-target'; b.style.cssText=`left:${left+i*(width+gap)}px;top:${top}px;width:${width}px;height:${height}px;border-radius:10px;font-size:24px;border-color:${i===expected?'#8bd5f5':'#58647a'}`; b.textContent=i===expected?'Pogledaj':'Drugo'; if(i===expected) {const progress=document.createElement('i');progress.className='check-trial-progress';b.append(progress);} targets.append(b); }
    checkEl('check-test-next').textContent=checkTrialIndex<2?'Sljedeća probna grupa':'Prikaži primjer rezultata';
  } else {
    checkEl('check-test-next').textContent='Prikaži primjer rezultata';
    for (const y of (mode==='free'?[.06,.5,.94]:[.5])) for (const x of (mode==='free'?[.04,.5,.96]:[.5])) { const dot=document.createElement('span'); dot.className='check-target'; dot.style.left=`calc(${x*100}% - 36px)`; dot.style.top=`calc(${y*100}% - 36px)`; dot.textContent='+'; targets.append(dot); }
  }
  checkEl('check-progress').hidden=mode!=='precision';
  checkEl('check-test-copy').innerHTML=mode==='free'?'Gledajte križiće redom. Zelena oznaka pokazuje vaš pogled.':mode==='trial'?`Dugme ${checkTrialIndex+1} od 3 · Gledajte „Pogledaj“.<br><span class="muted">Zadržite pogled dok se traka ne popuni.</span>`:'Meta 1 od 5 · Gledajte križić u krugu.<br><span class="muted">Meta se mijenja sama; ne trebate kliknuti.</span>';
  }
  checkEl('check-next').addEventListener('click',()=>checkStage(checkMode==='results'?'trial':'precision'));
  checkEl('check-free').addEventListener('click',()=>checkStage('free'));
  checkEl('check-test-next').addEventListener('click',()=>{ if(checkMode==='trial' && checkTrialIndex<2) { checkTrialIndex++; checkStage('trial'); return; } if(checkMode==='trial') { checkEl('check-trial-result').hidden=false; checkEl('check-trial-result').textContent='! Probni izbor: 3/3 · pogrešni izbori: 1'; checkEl('check-next').textContent='Ponovi probu dugmadi'; } else checkEl('check-next').textContent='Probaj izbor dugmeta'; checkMode='results'; checkEl('check-step').textContent='Rezultat provjere'; checkEl('check-test').hidden=true; checkEl('check-results').hidden=false; checkEl('check-reset').textContent='Podesi položaj'; checkEl('check-reset').hidden=false; checkResultTable(); });
  checkEl('check-details').addEventListener('click',()=>{checkDetails=!checkDetails;checkResultTable();});
  checkEl('check-test-back').addEventListener('click',checkReset);
  checkEl('check-reset').addEventListener('click',checkReset);
  // Installed settings candidates are tried in rank order. A broken shortcut must
  // not hide another installed Core settings UI; failure retains the manual tray route.
  // Settings and legacy calibration both exclude maintenance tools before ranking.
  checkEl('check-calibrate').addEventListener('click',()=>{ checkReset(); checkEl('check-notice').textContent='U Tobii Core odaberite profil korisnika > Test and recalibrate > Recalibrate. Vratite se ovdje i ponovite provjeru.'; });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || event.target.closest('.reference-switcher')) return;
    if (!checkEl('check-test').hidden) checkReset();
    else ReferenceDesign.returnTo();
  });
  checkReset();
  
})();
