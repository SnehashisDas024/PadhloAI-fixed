// ===== THEME =====
const themeToggle = () => {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
  document.querySelectorAll('.theme-icon').forEach(el => {
    el.textContent = next === 'dark' ? '☀️' : '🌙';
  });
};

const initTheme = () => {
  const saved = localStorage.getItem('theme') || 'light';
  document.documentElement.setAttribute('data-theme', saved);
  document.querySelectorAll('.theme-icon').forEach(el => {
    el.textContent = saved === 'dark' ? '☀️' : '🌙';
  });
};

// ===== TOAST =====
const showToast = (msg, type = 'info', duration = 3500) => {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${icons[type]}</span>
    <span class="toast-msg">${msg}</span>
    <span class="toast-close" onclick="removeToast(this.parentElement)">✕</span>
  `;
  container.appendChild(toast);
  setTimeout(() => removeToast(toast), duration);
};

const removeToast = (toast) => {
  toast.classList.add('removing');
  setTimeout(() => toast.remove(), 300);
};

// ===== MOBILE MENU =====
const initMobileMenu = () => {
  const sidebar = document.querySelector('.sidebar');
  const overlay = document.querySelector('.sidebar-overlay');
  const menuBtn = document.querySelector('.mobile-menu-btn');
  
  if (!sidebar) return;

  const openMenu = () => {
    sidebar.classList.add('open');
    overlay.classList.add('show');
    document.body.style.overflow = 'hidden';
  };
  const closeMenu = () => {
    sidebar.classList.remove('open');
    overlay.classList.remove('show');
    document.body.style.overflow = '';
  };

  menuBtn?.addEventListener('click', openMenu);
  overlay?.addEventListener('click', closeMenu);
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      if (window.innerWidth <= 768) closeMenu();
    });
  });
};

// ===== ACTIVE NAV =====
const setActiveNav = () => {
  const current = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav-item').forEach(item => {
    const href = item.getAttribute('href');
    if (href && (href === current || href.endsWith(current))) {
      item.classList.add('active');
    }
  });
};

// ===== SKELETON LOADER =====
const showSkeletons = (container, count = 3) => {
  container.innerHTML = Array(count).fill('').map(() => `
    <div class="card" style="height:100px">
      <div class="skeleton" style="height:16px;width:60%;margin-bottom:12px"></div>
      <div class="skeleton" style="height:12px;width:40%"></div>
    </div>
  `).join('');
};

// ===== ANIMATIONS: stagger cards =====
const animateCards = () => {
  const cards = document.querySelectorAll('.card, .glass');
  cards.forEach((card, i) => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(20px)';
    setTimeout(() => {
      card.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
      card.style.opacity = '1';
      card.style.transform = 'translateY(0)';
    }, i * 60);
  });
};

// ===== PROGRESS BARS =====
const animateProgress = () => {
  document.querySelectorAll('.progress-fill[data-width]').forEach(bar => {
    setTimeout(() => {
      bar.style.width = bar.dataset.width;
    }, 300);
  });
};

// ===== INIT =====
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initMobileMenu();
  setActiveNav();
  animateCards();
  animateProgress();

  document.querySelectorAll('.theme-btn').forEach(btn => {
    btn.addEventListener('click', themeToggle);
  });
});

// Export for inline use
window.showToast = showToast;
window.themeToggle = themeToggle;