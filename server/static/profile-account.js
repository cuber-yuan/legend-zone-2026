(() => {
  const open = document.getElementById('btn-account-settings');
  if (!open) return;
  const modal = document.getElementById('account-settings-modal');
  const form = document.getElementById('account-password-form');
  const current = document.getElementById('current-password');
  const password = document.getElementById('new-password');
  const confirm = document.getElementById('confirm-new-password');
  const feedback = document.getElementById('account-password-feedback');
  const save = document.getElementById('account-password-save');
  const close = document.getElementById('account-settings-close');
  const cancel = document.getElementById('account-settings-cancel');
  let busy = false;
  let previousOverflow = '';

  function showFeedback(message, error = false) {
    feedback.textContent = message;
    feedback.dataset.error = String(error);
    feedback.hidden = false;
  }

  function closeModal() {
    if (busy) return;
    modal.classList.add('hidden');
    form.reset();
    feedback.hidden = true;
    document.body.style.overflow = previousOverflow;
    open.focus();
  }

  open.addEventListener('click', () => {
    form.reset();
    feedback.hidden = true;
    previousOverflow = document.body.style.overflow;
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    current.focus();
  });
  close.addEventListener('click', closeModal);
  cancel.addEventListener('click', closeModal);
  modal.addEventListener('click', event => {
    if (event.target === modal) closeModal();
  });
  modal.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeModal();
    }
    if (event.key === 'Tab') {
      const focusable = Array.from(modal.querySelectorAll('button:not(:disabled), input:not(:disabled)'));
      const first = focusable[0], last = focusable.at(-1);
      if (!first) {
        event.preventDefault();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    feedback.hidden = true;
    if (password.value !== confirm.value) {
      showFeedback('New passwords do not match.', true);
      confirm.focus();
      return;
    }
    const body = JSON.stringify({
      current_password: current.value,
      new_password: password.value,
      confirm_password: confirm.value,
    });
    busy = true;
    form.setAttribute('aria-busy', 'true');
    form.querySelectorAll('input, button').forEach(element => { element.disabled = true; });
    close.disabled = true;
    save.textContent = 'Saving…';
    modal.focus();
    try {
      const response = await platformFetch('/api/account/password', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        showFeedback(typeof data.detail === 'string' ? data.detail : 'Unable to change your password. Please try again.', true);
      } else {
        form.reset();
        showFeedback(data.message || 'Password updated successfully.');
      }
    } catch {
      showFeedback('Unable to connect. Please try again.', true);
    } finally {
      busy = false;
      form.removeAttribute('aria-busy');
      form.querySelectorAll('input, button').forEach(element => { element.disabled = false; });
      close.disabled = false;
      save.textContent = 'Save Changes';
      current.focus();
    }
  });
})();
