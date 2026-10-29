(() => {
  async function writeText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    const focused = document.activeElement;
    document.body.appendChild(textarea);
    try {
      textarea.select();
      if (!document.execCommand('copy')) throw new Error(I18n.t('copy command rejected'));
    } finally {
      textarea.remove();
      focused?.focus({preventScroll: true});
    }
  }
  window.PlatformClipboard = Object.freeze({writeText});
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-copy-bot-id]').forEach(button => {
      const symbol = button.querySelector('[data-copy-symbol]');
      const status = button.parentElement.querySelector('[data-copy-status]');
      const originalPath = symbol.getAttribute('d');
      let reset, busy = false;
      button.addEventListener('click', async () => {
        if (busy) return;
        clearTimeout(reset);
        busy = true;
        try {
          await writeText(button.dataset.botId);
          symbol.setAttribute('d', 'm5 12 4 4L19 6');
          status.textContent = I18n.t('Copied!');
        } catch {
          symbol.setAttribute('d', originalPath);
          status.textContent = I18n.t('Copy failed');
        } finally {
          busy = false;
        }
        button.title = status.textContent;
        reset = setTimeout(() => {
          symbol.setAttribute('d', originalPath);
          button.title = I18n.t('Copy Bot ID');
          status.textContent = '';
        }, 1500);
      });
    });
  });
})();
