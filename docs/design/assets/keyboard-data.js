(() => {
  'use strict';
  const GROUPS = [
    ['A', 'B', 'C', 'Č', 'Ć'], ['D', 'DŽ', 'Đ', 'E', 'F'],
    ['G', 'H', 'I', 'J', 'K'], ['L', 'LJ', 'M', 'N', 'NJ'],
    ['O', 'P', 'R', 'S', 'Š'], ['T', 'U', 'V', 'Z', 'Ž']
  ];

  const ARABIC_LETTERS = [...'ابتثجحخدذرزسشصضطظعغفقكلمنهويءآأؤإئةىٱ'];
  const ARABIC_MARKS = Array.from({length: 21}, (_, index) => String.fromCodePoint(0x64b + index)).concat('ٰ', [...'ۣ۪ۭۖۗۘۙۚۛۜ۟۠ۡۢۤۧۨ۫۬']);
  const ARABIC_SYMBOLS = [...'1234567890٠١٢٣٤٥٦٧٨٩.,،؟؛!:%٪-+/=()«»', ...ARABIC_MARKS];
  const grouped = (keys, size = 5) => Array.from({length: Math.ceil(keys.length / size)}, (_, index) => keys.slice(index * size, index * size + size));
  const keyLabel = key => /\p{Mark}/u.test(key[0]) ? '◌' + key : key;
  const SYMBOLS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '.', '?'];
  const ARABIC_SPEECH_SYMBOLS = [...new Set([...SYMBOLS, ...ARABIC_SYMBOLS])];
  const SIDEBAR_SYMBOLS = [...'.,@/?!$%&*()-_+=:;', "'", '"', '#', '\\', ...'|<>[]{}~`^'];
  const SIDEBAR_NUMPAD = [...'7894561230.', 'Potvrdi', ...'+-*/='];
  const readScript = () => {
    try { return localStorage.getItem('pogled-assist-design-script') === 'arabic'; }
    catch { return false; }
  };
  const writeScript = arabic => {
    try { localStorage.setItem('pogled-assist-design-script', arabic ? 'arabic' : 'latin'); } catch {}
  };
  window.ReferenceKeyboard = Object.freeze({ GROUPS, ARABIC_LETTERS, ARABIC_SYMBOLS, SYMBOLS, ARABIC_SPEECH_SYMBOLS, SIDEBAR_SYMBOLS, SIDEBAR_NUMPAD, grouped, keyLabel, readScript, writeScript });
})();
