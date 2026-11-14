(() => {
  'use strict';
  // Illustrative only: a selection marks the tile and names the action.
  const status = document.querySelector('#quick-status');
  const grid = document.querySelector('.quick-grid');
  const scrolls = new Set(['Pomjeri gore', 'Pomjeri dolje']);
  for (const button of document.querySelectorAll('[data-quick-action]')) {
    button.addEventListener('click', () => {
      document.querySelectorAll('[data-selected]').forEach(item => item.removeAttribute('data-selected'));
      const action = button.dataset.quickAction;
      if (!scrolls.has(action)) {
        button.setAttribute('data-selected', '');
        status.textContent = 'Odabrano: ' + action + '. Meni se zatvara i radnja se izvršava na odabranoj tački.';
        return;
      }
      // Scrolling hides the grid for the pause between actions, then the same grid returns.
      grid.setAttribute('data-repeat-wait', '');
      status.textContent = 'Odabrano: ' + action + '. Mreža se skloni dok se sadržaj pomjeri.';
      window.setTimeout(() => {
        grid.removeAttribute('data-repeat-wait');
        status.textContent = 'Ista mreža je ponovo na istoj tački. Za još jedno pomjeranje pogledajte drugo mjesto, pa ponovo ' + action + '.';
      }, 350);
    });
  }
})();
