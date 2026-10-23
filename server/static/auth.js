(() => {
  const form = document.querySelector('.auth-form');
  const feedback = document.getElementById('auth-feedback');
  const submit = form.querySelector("button[type=\"submit\"]");
  const registering = form.dataset.operation === 'register';
  const label = submit.textContent;

  function showError(message) {
    feedback.textContent = message;
    feedback.hidden = false;
    feedback.focus();
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (submit.disabled) return;
    feedback.hidden = true;
    const data = new URLSearchParams(new FormData(form));
    if (registering) {
      data.set('username', data.get('username').trim());
      data.set('email', data.get('email').trim());
      if (data.get('username').length < 4) {
        showError(I18n.t("Username must be at least 4 characters."));
        return;
      }
      if (data.get('password') !== data.get('confirm_password')) {
        showError(I18n.t("Passwords do not match."));
        return;
      }
    }

    submit.disabled = true;
    submit.textContent = registering ? I18n.t("Registering…") : I18n.t("Logging in…");
    form.setAttribute('aria-busy', 'true');
    try {
      const response = await platformFetch(form.action, {
        method: 'POST',
        body: data,
      });
      if (response.ok) {
        window.location.assign(I18n.url('/'));
        return;
      }
      const result = await response.json().catch(() => ({}));
      showError(typeof result.detail === 'string' ? I18n.t(result.detail) :
        (registering ? I18n.t("Registration failed. Please check your details and try again.") :
          I18n.t("Login failed. Please check your credentials and try again.")));
    } catch {
      showError(I18n.t("Unable to connect. Please try again."));
    } finally {
      submit.disabled = false;
      submit.textContent = label;
      form.removeAttribute('aria-busy');
    }
  });
})();
