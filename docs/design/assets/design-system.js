(() => {
  'use strict';
  const font = document.getElementById('preview-font');
  font.value = document.documentElement.dataset.previewFont;
  font.addEventListener('change', () => {
    document.documentElement.dataset.previewFont = font.value;
    ReferenceDesign.writeSession('preview-font', font.value);
    ReferenceDesign.refreshLinks();
  });
  const toggle = document.getElementById('sample-switch');
  toggle.addEventListener('change', () => {
    document.getElementById('sample-switch-state').textContent = toggle.checked ? 'Uključeno' : 'Isključeno';
  });
  for (const button of document.querySelectorAll('.sample-navigation button')) {
    button.addEventListener('click', () => {
      for (const choice of button.parentElement.children) choice.removeAttribute('aria-current');
      button.setAttribute('aria-current', 'page');
    });
  }
  const tabs = [...document.querySelectorAll('.sample-tabs [role="tab"]')];
  function selectTab(button) {
    for (const tab of tabs) {
      tab.setAttribute('aria-selected', String(tab === button));
      tab.tabIndex = tab === button ? 0 : -1;
      document.getElementById(tab.getAttribute('aria-controls')).hidden = tab !== button;
    }
  }
  tabs.forEach((button, index) => {
    button.addEventListener('click', () => selectTab(button));
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      selectTab(tabs[next]);
      tabs[next].focus();
    });
  });
})();
