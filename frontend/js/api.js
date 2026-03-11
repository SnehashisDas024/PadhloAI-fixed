// api.js — All backend API calls for PadhloAI
// Backend runs at: http://localhost:8000
// All authenticated requests include the JWT token from localStorage

const API_BASE = 'http://localhost:8000';

// ─── Token helpers ────────────────────────────────────────────────

const Auth = {
  getToken: () => localStorage.getItem('padhlo_token'),
  getUser:  () => JSON.parse(localStorage.getItem('padhlo_user') || 'null'),
  setSession: (token, user) => {
    localStorage.setItem('padhlo_token', token);
    localStorage.setItem('padhlo_user', JSON.stringify(user));
  },
  clearSession: () => {
    localStorage.removeItem('padhlo_token');
    localStorage.removeItem('padhlo_user');
  },
  isLoggedIn: () => !!localStorage.getItem('padhlo_token'),
};

// ─── Base fetch wrapper ───────────────────────────────────────────

async function apiFetch(path, options = {}) {
  const token = Auth.getToken();
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  // Don't set Content-Type for FormData (let browser set boundary)
  if (options.body instanceof FormData) delete headers['Content-Type'];

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    Auth.clearSession();
    window.location.href = 'login.html';
    return;
  }

  const data = res.headers.get('content-type')?.includes('application/json')
    ? await res.json()
    : await res.text();

  if (!res.ok) {
    const msg = data?.detail || data || `HTTP ${res.status}`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data;
}

// ─── Auth API ─────────────────────────────────────────────────────

const AuthAPI = {
  async login(username, password) {
    // FastAPI OAuth2 expects form-encoded body
    const form = new URLSearchParams();
    form.append('username', username);
    form.append('password', password);
    const res = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Login failed');
    return data; // { access_token, token_type, username, user_id }
  },

  async register(username, email, password) {
    return apiFetch('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username, email, password }),
    });
  },
};

// ─── Documents API ────────────────────────────────────────────────

const DocumentsAPI = {
  async upload(file, onProgress) {
    const token = Auth.getToken();
    const formData = new FormData();
    formData.append('file', file);

    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${API_BASE}/api/documents/upload`);
      xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      if (onProgress) xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status === 201) resolve(data);
        else reject(new Error(data.detail || 'Upload failed'));
      };
      xhr.onerror = () => reject(new Error('Network error during upload'));
      xhr.send(formData);
    });
  },

  async list() {
    return apiFetch('/api/documents/');
  },

  async delete(id) {
    return apiFetch(`/api/documents/${id}`, { method: 'DELETE' });
  },
};

// ─── Chat API ─────────────────────────────────────────────────────

const ChatAPI = {
  async sendMessage(message, documentId = null) {
    return apiFetch('/api/chat/message', {
      method: 'POST',
      body: JSON.stringify({ message, document_id: documentId }),
    });
  },
};

// ─── Tests API ────────────────────────────────────────────────────

const TestsAPI = {
  async generate(documentId) {
    return apiFetch('/api/tests/generate', {
      method: 'POST',
      body: JSON.stringify({ document_id: documentId }),
    });
  },

  async submit(documentId, answers, questions) {
    return apiFetch('/api/tests/submit', {
      method: 'POST',
      body: JSON.stringify({ document_id: documentId, answers, questions }),
    });
  },

  async results() {
    return apiFetch('/api/tests/results');
  },
};

// ─── Analytics API ────────────────────────────────────────────────

const AnalyticsAPI = {
  async summary() {
    return apiFetch('/api/analytics/summary');
  },
};

// ─── Auth guard: redirect to login if not authenticated ───────────
// Call this at the top of any protected page

function requireAuth() {
  if (!Auth.isLoggedIn()) {
    window.location.href = 'login.html';
    return false;
  }
  // Patch the sidebar user card with real user data
  document.addEventListener('DOMContentLoaded', () => {
    const user = Auth.getUser();
    if (!user) return;
    const nameEl = document.querySelector('.user-name');
    const roleEl = document.querySelector('.user-role');
    const avatarEls = document.querySelectorAll('.avatar');
    if (nameEl) nameEl.textContent = user.username;
    if (roleEl) roleEl.textContent = 'Student';
    const initials = user.username.substring(0, 2).toUpperCase();
    avatarEls.forEach(el => { if (!el.querySelector('img')) el.textContent = initials; });
  });
  return true;
}

// ─── Export ───────────────────────────────────────────────────────
window.Auth = Auth;
window.AuthAPI = AuthAPI;
window.DocumentsAPI = DocumentsAPI;
window.ChatAPI = ChatAPI;
window.TestsAPI = TestsAPI;
window.AnalyticsAPI = AnalyticsAPI;
window.requireAuth = requireAuth;
