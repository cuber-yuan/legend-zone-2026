(() => {
  const locale = document.documentElement.lang.startsWith('zh') ? 'zh' : 'en';
  const messages = JSON.parse(document.getElementById('i18n-messages').textContent);
  function t(key, ...values) {
    const text = Object.hasOwn(messages, String(key)) ? messages[String(key)] : String(key);
    return text.replace(/\{(\d+)\}/g, (match, index) => index < values.length ? String(values[index]) : match);
  }
  function url(value) {
    if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return value;
    if (/^\/(?:en|zh)(?:\/|$)/.test(value)) return value;
    if (/^\/(?:api|static)(?:\/|$)/.test(value)) return value;
    const path = value.split(/[?#]/, 1)[0];
    if (!/^\/(?:|games|matches|rating|chat|login|register|profile|upload|admin|gomoku|tictactoe|connect4|snake|msnake|tank|yahtzee|injoker|catking|profile\/[^/]+|bot\/[^/]+(?:\/new-version)?|bots\/[^/]+\/new-version|match\/[^/]+)$/.test(path)) return value;
    return '/' + locale + value;
  }
  window.I18n = Object.freeze({locale, t, url});
  document.addEventListener('click', event => {
    const link = event.target.closest('#language-switch');
    if (!link) return;
    const path = location.pathname.replace(/^\/(?:en|zh)(?=\/|$)/, '') || '/';
    link.href = '/' + (locale === 'en' ? 'zh' : 'en') + path + location.search + location.hash;
  }, true);
})();
