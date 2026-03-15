// ─── 토스트 알림 ──────────────────────────────────────

let toastTimer = null;

function showToast(message, type = 'info') {
  let el = document.getElementById('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.className = `show ${type}`;

  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3500);
}

// ─── 패스워드 토글 ────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('input[type="password"]').forEach(input => {
    const wrapper = document.createElement('div');
    wrapper.style.cssText = 'position:relative;display:flex;align-items:center;';
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.textContent = '👁';
    toggle.style.cssText = `
      position:absolute; right:8px; background:none; border:none;
      cursor:pointer; font-size:14px; padding:0; color:#64748b;
    `;
    toggle.onclick = () => {
      input.type = input.type === 'password' ? 'text' : 'password';
    };
    // input-with-btn 안에 있으면 적용 안 함
    if (!input.closest('.input-with-btn')) {
      wrapper.appendChild(toggle);
      input.style.paddingRight = '32px';
    }
  });
});
