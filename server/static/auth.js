(() => {
  const form = document.querySelector('.auth-form');
  const feedback = document.getElementById('auth-feedback');
  const submit = form.querySelector('button[type="submit"]');
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
        showError('Username must be at least 4 characters.');
        return;
      }
      if (data.get('password') !== data.get('confirm_password')) {
        showError('Passwords do not match.');
        return;
      }
    }

    submit.disabled = true;
    submit.textContent = registering ? 'Registering…' : 'Logging in…';
    form.setAttribute('aria-busy', 'true');
    try {
      const response = await platformFetch(form.action, {
        method: 'POST',
        body: data,
      });
      if (response.ok) {
        window.location.assign('/');
        return;
      }
      const result = await response.json().catch(() => ({}));
      showError(typeof result.detail === 'string' ? result.detail :
        (registering ? 'Registration failed. Please check your details and try again.' :
          'Login failed. Please check your credentials and try again.'));
    } catch {
      showError('Unable to connect. Please try again.');
    } finally {
      submit.disabled = false;
      submit.textContent = label;
      form.removeAttribute('aria-busy');
    }
  });
})();
