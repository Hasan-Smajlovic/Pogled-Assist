(() => {
  'use strict';
  const { GROUPS, ARABIC_LETTERS, ARABIC_SYMBOLS, SIDEBAR_SYMBOLS, SIDEBAR_NUMPAD, grouped, keyLabel, readScript, writeScript } = ReferenceKeyboard;
  const $ = id => document.getElementById(id);
  const gazeDemo = document.getElementById('gaze-demo') ? createReferenceGaze() : { reset() {} };
  let arabic = readScript();
  let sideTab = 'letters', sidePage = 0, sideGroup = null, sideGroupSize = 5;
  if (document.body.dataset.referencePage === 'sidebar') {
    document.querySelectorAll('.sidebar-reference button').forEach(button => button.setAttribute('data-edge-control', ''));
  }
  $('sidebar-group-size').addEventListener('change', event => {
    sideGroupSize = Number(event.target.value); sidePage = 0; sideGroup = null; renderSidebars(); gazeDemo.reset();
  });
  for (const button of document.querySelectorAll('[data-side-tab]')) button.addEventListener('click', () => {
    sideTab = button.dataset.sideTab; sidePage = 0; sideGroup = null; renderSidebars(); gazeDemo.reset();
  });
  for (const button of document.querySelectorAll('[data-side-page]')) button.addEventListener('click', () => {
    sidePage += Number(button.dataset.sidePage); sideGroup = null; renderSidebars(); gazeDemo.reset();
  });
  for (const button of document.querySelectorAll('[data-side-back]')) button.addEventListener('click', () => {
    sideGroup = null; renderSidebars(); gazeDemo.reset();
  });
  for (const button of document.querySelectorAll('[data-script-toggle]')) button.addEventListener('click', () => {
    arabic = !arabic; writeScript(arabic); sidePage = 0; sideGroup = null; renderSidebars(); gazeDemo.reset();
  });
  function renderSidebars() {
    for (const button of document.querySelectorAll('[data-script-toggle]')) button.textContent = arabic ? 'Latinica' : 'Arapski';
    const keys = sideTab === 'letters' ? grouped(arabic ? ARABIC_LETTERS : GROUPS.flat(), sideGroupSize) : grouped(sideTab === 'numbers' ? [...SIDEBAR_NUMPAD, ...(arabic ? [...'٠١٢٣٤٥٦٧٨٩'] : [])] : arabic ? [...new Set([...SIDEBAR_SYMBOLS, ...ARABIC_SYMBOLS])] : SIDEBAR_SYMBOLS, arabic ? Math.max(5, sideGroupSize) : sideGroupSize);
    const pages = Math.max(1, Math.ceil(keys.length / 8));
    sidePage = Math.max(0, Math.min(sidePage, pages - 1));
    for (const grid of document.querySelectorAll('.sidebar-reference-grid')) {
      grid.dir = arabic && (sideGroup === null || sideTab === 'letters') ? 'rtl' : 'ltr';
      grid.style.gridTemplateColumns = `repeat(${sideGroup === null ? 2 : 3}, 1fr)`;
      const visible = sideGroup === null ? keys.slice(sidePage * 8, sidePage * 8 + 8) : keys[sideGroup];
      grid.replaceChildren(...visible.map((item, index) => {
        const button = document.createElement('button'); button.type = 'button';
        button.textContent = sideGroup === null ? (arabic || item.length > 5 ? item.map(keyLabel).reduce((rows, label, index) => { if (index % 3 === 0) rows.push([]); rows.at(-1).push(label); return rows; }, []).map(row => row.join(' ')).join('\n') : item.join(' ')) : keyLabel(item);
        if (document.body.dataset.referencePage === 'sidebar') button.setAttribute('data-edge-control', '');
        button.onclick = () => { if (sideGroup === null) sideGroup = sidePage * 8 + index; else sideGroup = null; renderSidebars(); gazeDemo.reset(); };
        return button;
      }));
      const navigation = grid.parentElement.querySelector('.sidebar-pages');
      navigation.hidden = pages <= 1 || sideGroup !== null;
      navigation.querySelector('[data-side-page="-1"]').disabled = sidePage === 0;
      navigation.querySelector('[data-side-page="1"]').disabled = sidePage + 1 === pages;
      const back = grid.parentElement.querySelector('[data-side-back]');
      back.hidden = sideGroup === null;
      back.parentElement.style.gridTemplateColumns = sideGroup === null ? 'repeat(2, 1fr)' : '1fr 2fr 2fr';
    }
  }
  renderSidebars();
})();
