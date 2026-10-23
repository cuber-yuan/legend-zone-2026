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
  const avatarForm = document.getElementById('account-avatar-form');
  const avatarFile = document.getElementById('account-avatar-file');
  const avatarPreview = document.getElementById('account-avatar-preview');
  const avatarSave = document.getElementById('account-avatar-save');
  const avatarRemove = document.getElementById('account-avatar-remove');
  const avatarFeedback = document.getElementById('account-avatar-feedback');
  const defaultAvatar = '/static/default-avatar.png';
  let avatarUrl = avatarForm.dataset.avatarUrl || null;
  let previewUrl = null;
  let busy = false;
  let previousOverflow = '';

  function avatarControls() {
    avatarSave.disabled = busy || !avatarFile.files.length;
    avatarRemove.disabled = busy || !avatarUrl;
  }

  function clearPreview() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    avatarForm.reset();
    avatarPreview.src = avatarUrl || defaultAvatar;
    avatarControls();
  }

  function setBusy(value) {
    busy = value;
    modal.querySelectorAll("input, button").forEach(element => { element.disabled = value; });
    avatarControls();
  }

  avatarFile.addEventListener('change', () => {
    avatarFeedback.hidden = true;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    const file = avatarFile.files[0];
    if (file && (file.size > 4 * 1024 * 1024 || !["image/png", "image/jpeg", "image/webp"].includes(file.type))) {
      avatarFeedback.textContent = I18n.t("Choose a PNG, JPEG or WebP image up to 4 MiB.");
      avatarFeedback.dataset.error = 'true';
      avatarFeedback.hidden = false;
      clearPreview();
      return;
    }
    if (file) previewUrl = URL.createObjectURL(file);
    avatarPreview.src = previewUrl || avatarUrl || defaultAvatar;
    avatarControls();
  });

  async function updateAvatar(removing) {
    if (busy || (!removing && !avatarFile.files.length)) return;
    const body = new FormData();
    if (!removing) body.append('file', avatarFile.files[0]);
    setBusy(true);
    avatarForm.setAttribute('aria-busy', 'true');
    avatarFeedback.hidden = true;
    modal.focus();
    try {
      const response = await platformFetch('/api/account/avatar', {
        method: removing ? 'DELETE' : 'POST', ...(removing ? {} : {body}),
      });
      if (response.redirected) throw new Error(I18n.t("Your session has expired. Please sign in again."));
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? I18n.t(data.detail) : I18n.t("Unable to update your avatar. Please try again."));
      avatarUrl = data.avatar_url ? `${data.avatar_url}?v=${Date.now()}` : null;
      document.querySelectorAll("[data-own-avatar]").forEach(image => {
        image.src = avatarUrl || defaultAvatar;
        if (image.closest('.nav-avatar')) image.hidden = !avatarUrl;
      });
      document.querySelectorAll("[data-avatar-initial]").forEach(initial => { initial.hidden = Boolean(avatarUrl); });
      clearPreview();
      avatarFeedback.textContent = I18n.t(data.message);
      avatarFeedback.dataset.error = 'false';
    } catch (error) {
      avatarFeedback.textContent = I18n.t(error.message);
      avatarFeedback.dataset.error = 'true';
    } finally {
      avatarFeedback.hidden = false;
      avatarForm.removeAttribute('aria-busy');
      setBusy(false);
      avatarFile.focus();
    }
  }
  avatarForm.addEventListener('submit', event => { event.preventDefault(); updateAvatar(false); });
  avatarRemove.addEventListener('click', () => updateAvatar(true));

  function showFeedback(message, error = false) {
    feedback.textContent = message;
    feedback.dataset.error = String(error);
    feedback.hidden = false;
  }

  function closeModal() {
    if (busy) return;
    modal.classList.add('hidden');
    form.reset();
    clearPreview();
    avatarFeedback.hidden = true;
    feedback.hidden = true;
    document.body.style.overflow = previousOverflow;
    open.focus();
  }

  open.addEventListener('click', () => {
    form.reset();
    clearPreview();
    avatarFeedback.hidden = true;
    feedback.hidden = true;
    previousOverflow = document.body.style.overflow;
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    avatarFile.focus();
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
      const focusable = Array.from(modal.querySelectorAll("button:not(:disabled), input:not(:disabled)"));
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
      showFeedback(I18n.t("New passwords do not match."), true);
      confirm.focus();
      return;
    }
    const body = JSON.stringify({
      current_password: current.value,
      new_password: password.value,
      confirm_password: confirm.value,
    });
    setBusy(true);
    form.setAttribute('aria-busy', 'true');
    form.querySelectorAll("input, button").forEach(element => { element.disabled = true; });
    close.disabled = true;
    save.textContent = I18n.t("Saving…");
    modal.focus();
    try {
      const response = await platformFetch('/api/account/password', {
        method: 'POST',
        headers: {'Content-Type': "application/json"},
        body,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        showFeedback(typeof data.detail === 'string' ? I18n.t(data.detail) : I18n.t("Unable to change your password. Please try again."), true);
      } else {
        form.reset();
        showFeedback(data.message || I18n.t("Password updated successfully."));
      }
    } catch {
      showFeedback(I18n.t("Unable to connect. Please try again."), true);
    } finally {
      setBusy(false);
      form.removeAttribute('aria-busy');
      form.querySelectorAll("input, button").forEach(element => { element.disabled = false; });
      close.disabled = false;
      save.textContent = I18n.t("Save Password");
      current.focus();
    }
  });
})();
