(() => {
  'use strict';
  // Illustrative only: a selection marks the tile and names the action.
  const status = document.querySelector('#quick-status');
  for (const button of document.querySelectorAll('[data-quick-action]')) {
    button.addEventListener('click', () => {
      document.querySelectorAll('[data-selected]').forEach(item => item.removeAttribute('data-selected'));
      button.setAttribute('data-selected', '');
      status.textContent = 'Odabrano: ' + button.dataset.quickAction + '. Meni se zatvara i radnja se izvršava na odabranoj tački.';
    });
  }
})();
