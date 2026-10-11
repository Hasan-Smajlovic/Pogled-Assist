(() => {
  'use strict';
  const pages = [
    ['hotbar', 'hotbar.html', 'Početni meni'],
    ['sidebar', 'keyboard.html', 'Tastatura'],
    ['controller', 'controller-keyboard.html', 'Upravljač: tastatura'],
    ['speech', 'speech.html', 'Govor'],
    ['settings', 'settings.html', 'Postavke'],
    ['installation', 'installation.html', 'Instalacija'],
    ['gaze-check', 'gaze-check.html', 'Provjera pogleda'],
    ['tracking', 'tracking.html', 'Praćenje'],
  ];
  const currentPage = document.body.dataset.referencePage;
  const query = new URLSearchParams(location.search);
  const memory = new Map();
  function readSession(key, fallback) {
    try { return JSON.parse(sessionStorage.getItem('pogled-assist-reference-' + key)) ?? fallback; }
    catch { return memory.get(key) ?? fallback; }
  }
  function writeSession(key, value) {
    memory.set(key, value);
    try { sessionStorage.setItem('pogled-assist-reference-' + key, JSON.stringify(value)); } catch {}
  }
  if (query.has('feedback')) writeSession('feedback', query.get('feedback') !== 'off');
  function pageUrl(key, params = {}) {
    const page = pages.find(item => item[0] === key);
    if (!page) throw new Error('Unknown reference page: ' + key);
    const url = new URL(page[1], location.href);
    if (!readSession('feedback', true)) url.searchParams.set('feedback', 'off');
    for (const [name, value] of Object.entries(params)) url.searchParams.set(name, value);
    return url.href;
  }
  function open(key, params) { location.assign(pageUrl(key, params)); }
  function returnTo() {
    const key = query.get('return');
    open(pages.some(page => page[0] === key) ? key : 'settings');
  }
  function refreshLinks() {
    for (const link of document.querySelectorAll('a[data-reference-link]')) {
      const url = new URL(pageUrl(link.dataset.referenceLink));
      if (link.dataset.referenceFragment) url.hash = link.dataset.referenceFragment;
      link.href = url.href;
    }
  }
  window.ReferenceDesign = Object.freeze({ readSession, writeSession, pageUrl, open, returnTo, refreshLinks });

  // Keep bookmarked links to the former single document working.
  function followLegacyHash() {
    if (currentPage !== 'index') return;
    const key = location.hash.slice(1);
    if (key === 'marker') {
      location.replace(pageUrl('hotbar') + '#marker-screen');
      return;
    }
    if (pages.some(page => page[0] === key)) location.replace(pageUrl(key));
  }
  followLegacyHash();
  window.addEventListener('hashchange', followLegacyHash);

  const navigation = document.querySelector('.reference-switcher');
  if (navigation) {
    const menu = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = 'Prikazi';
    const links = document.createElement('div');
    for (const [key, filename, title] of pages) {
      const link = document.createElement('a');
      link.href = filename;
      link.textContent = title;
      link.dataset.referenceLink = key;
      if (key === currentPage) link.setAttribute('aria-current', 'page');
      links.append(link);
    }
    const notes = document.createElement('a');
    notes.href = 'reference-notes.html';
    notes.textContent = 'O ovoj referenci';
    links.append(notes);
    menu.append(summary, links);
    navigation.append(menu);
  }
  refreshLinks();
  document.addEventListener('click', event => {
    const button = event.target.closest('button[data-open-view], button[data-reference-return]');
    if (!button) return;
    if (button.hasAttribute('data-reference-return')) returnTo();
    else open(button.dataset.openView);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      document.querySelectorAll('.reference-switcher details, .reference-tools').forEach(menu => { menu.open = false; });
    }
  });
})();
