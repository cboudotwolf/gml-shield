import './style.css';

type User = { id: number; email: string; role: 'ADMIN' | 'DISPATCHER' | 'DRIVER' };
type Mission = { id: number; title: string; destination: string; secret_code: string; status: string; driver_id: number; documents: string[] };
type Driver = { id: number; email: string; role: string };
const app = document.querySelector<HTMLMainElement>('#app')!;

function csrfToken(): string {
  return document.cookie.split('; ').find((part) => part.startsWith('gml_csrf='))?.split('=').slice(1).join('=') ?? '';
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (!['GET', 'HEAD'].includes(options.method ?? 'GET')) headers.set('X-CSRF-Token', decodeURIComponent(csrfToken()));
  const response = await fetch(path, { ...options, headers, credentials: 'same-origin' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Erreur ${response.status}`);
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}

function escapeHtml(value: string): string {
  const element = document.createElement('span');
  element.textContent = value;
  return element.innerHTML;
}

function showMessage(message: string, kind = ''): void {
  const target = document.querySelector<HTMLElement>('#message');
  if (target) { target.textContent = message; target.className = `message ${kind}`; }
}

function renderLogin(): void {
  app.innerHTML = `<section class="login-card"><div class="brand-mark">G</div><p class="eyebrow">GML · ESPACE SÉCURISÉ</p><h1>GML-SHIELD</h1><p class="muted">Connectez-vous pour accéder à vos missions.</p><form id="login-form"><label>Adresse e-mail<input name="email" type="email" autocomplete="username" required></label><label>Mot de passe<input name="password" type="password" autocomplete="current-password" minlength="12" required></label><button>Se connecter</button></form><p id="message" class="message" role="status"></p></section>`;
  document.querySelector<HTMLFormElement>('#login-form')!.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget as HTMLFormElement);
    try { await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ email: form.get('email'), password: form.get('password') }) }); await loadApp(); }
    catch (error) { showMessage(error instanceof Error ? error.message : 'Connexion impossible', 'error'); }
  });
}

function missionCard(mission: Mission, driver = false): string {
  const active = mission.status === 'IN_PROGRESS';
  const nextAction = mission.status === 'PENDING' ? 'IN_PROGRESS' : mission.status === 'IN_PROGRESS' && mission.documents.length ? 'COMPLETED' : '';
  const actionLabel = mission.status === 'PENDING' ? 'Commencer la mission' : 'Clôturer la mission';
  return `<article class="mission"><div class="mission-top"><span class="status ${mission.status.toLowerCase()}">${escapeHtml(mission.status)}</span><span class="muted">Mission #${mission.id}</span></div><h3>${escapeHtml(mission.title)}</h3><p><strong>Destination</strong><br>${escapeHtml(mission.destination)}</p>${driver ? `<div class="secret"><span>Code entrepôt</span><code id="secret-${mission.id}" data-value="${escapeHtml(mission.secret_code)}">••••••••</code><button class="text-button" data-reveal="${mission.id}">Afficher</button></div>` : ''}<div class="mission-actions">${driver && active ? `<label class="upload-button">Ajouter une preuve<input type="file" accept="image/jpeg,image/png,application/pdf" data-upload="${mission.id}"></label>` : ''}${driver && nextAction ? `<button class="secondary" data-status="${mission.id}" data-next="${nextAction}">${actionLabel}</button>` : ''}${!driver && mission.documents.length ? `<button class="secondary" data-download="${mission.id}" data-doc="${mission.documents[0]}">Télécharger la preuve</button>` : ''}</div></article>`;
}

async function showDispatcher(user: User): Promise<void> {
  const [missions, drivers] = await Promise.all([api<Mission[]>('/api/missions'), api<Driver[]>('/api/drivers')]);
  app.innerHTML = `<header class="topbar"><div><span class="brand-mark small">G</span><strong>GML-SHIELD</strong></div><div class="account">${escapeHtml(user.email)} <button id="logout" class="text-button">Déconnexion</button></div></header><section class="content"><p class="eyebrow">ESPACE RÉPARTITEUR</p><h1>Suivi des missions</h1><div class="columns"><section class="panel"><h2>Créer une mission</h2><form id="mission-form"><label>Intitulé<input name="title" required maxlength="120"></label><label>Destination<input name="destination" required maxlength="500"></label><label>Code entrepôt<input name="secret_code" required maxlength="200"></label><label>Chauffeur<select name="driver_id" required>${drivers.map((d) => `<option value="${d.id}">${escapeHtml(d.email)}</option>`).join('')}</select></label><button>Créer la mission</button></form><p id="message" class="message" role="status"></p></section><section><h2>Missions créées</h2><div class="mission-list">${missions.length ? missions.map((m) => missionCard(m)).join('') : '<p class="muted">Aucune mission.</p>'}</div></section></div></section>`;
  document.querySelector<HTMLFormElement>('#mission-form')!.addEventListener('submit', async (event) => {
    event.preventDefault(); const data = new FormData(event.currentTarget as HTMLFormElement);
    try { await api('/api/missions', { method: 'POST', body: JSON.stringify({ title: data.get('title'), destination: data.get('destination'), secret_code: data.get('secret_code'), driver_id: Number(data.get('driver_id')) }) }); await showDispatcher(user); showMessage('Mission créée et transmise au chauffeur.'); }
    catch (error) { showMessage(error instanceof Error ? error.message : 'Création impossible', 'error'); }
  });
  document.querySelectorAll<HTMLButtonElement>('[data-download]').forEach((button) => button.addEventListener('click', async () => { const response = await fetch(`/api/missions/${button.dataset.download}/documents/${button.dataset.doc}`, { credentials: 'same-origin' }); if (response.ok) { const blob = await response.blob(); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'preuve'; link.click(); URL.revokeObjectURL(link.href); } }));
}

async function showDriver(user: User): Promise<void> {
  const missions = await api<Mission[]>('/api/missions');
  app.innerHTML = `<header class="topbar"><div><span class="brand-mark small">G</span><strong>GML-SHIELD</strong></div><div class="account">${escapeHtml(user.email)} <span class="live-dot">Temps réel</span><button id="logout" class="text-button">Déconnexion</button></div></header><section class="content narrow"><p class="eyebrow">ESPACE CHAUFFEUR</p><h1>Mes missions</h1><p class="muted">Vos missions restent accessibles après une interruption réseau.</p><div class="mission-list" id="mission-list">${missions.length ? missions.map((m) => missionCard(m, true)).join('') : '<div class="empty">Aucune mission assignée.</div>'}</div><p id="message" class="message" role="status"></p></section>`;
  document.querySelectorAll<HTMLButtonElement>('[data-reveal]').forEach((button) => button.addEventListener('click', () => { const code = document.querySelector<HTMLElement>(`#secret-${button.dataset.reveal}`)!; const revealed = code.textContent !== '••••••••'; code.textContent = revealed ? '••••••••' : code.dataset.value!; button.textContent = revealed ? 'Afficher' : 'Masquer'; }));
  document.querySelectorAll<HTMLButtonElement>('[data-status]').forEach((button) => button.addEventListener('click', async () => { try { await api(`/api/missions/${button.dataset.status}/status`, { method: 'PATCH', body: JSON.stringify({ status: button.dataset.next }) }); await showDriver(user); } catch (error) { showMessage(error instanceof Error ? error.message : 'Mise à jour impossible', 'error'); } }));
  document.querySelectorAll<HTMLInputElement>('[data-upload]').forEach((input) => input.addEventListener('change', async () => { const file = input.files?.[0]; if (!file) return; const body = new FormData(); body.append('upload', file); try { await api(`/api/missions/${input.dataset.upload}/documents`, { method: 'POST', body }); await showDriver(user); showMessage('Preuve envoyée et contrôlée.'); } catch (error) { showMessage(error instanceof Error ? error.message : 'Envoi impossible', 'error'); } }));
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/ws`);
  ws.onmessage = async (event) => { const notification = JSON.parse(event.data); if (notification.event === 'NEW_MISSION') { await showDriver(user); showMessage('Une nouvelle mission vous a été assignée.'); } };
}

async function showAdmin(user: User): Promise<void> {
  const entries = await api<Array<{action:string;resource:string;result:string;created_at:string}>>('/api/audit');
  app.innerHTML = `<header class="topbar"><div><span class="brand-mark small">G</span><strong>GML-SHIELD</strong></div><div class="account">${escapeHtml(user.email)} <button id="logout" class="text-button">Déconnexion</button></div></header><section class="content"><p class="eyebrow">ADMINISTRATION DE SÉCURITÉ</p><h1>Journal d’audit</h1><section class="panel audit-list">${entries.map((e) => `<div class="audit-row"><span>${escapeHtml(e.action)}</span><span>${escapeHtml(e.resource)}</span><span class="status">${escapeHtml(e.result)}</span><time>${new Date(e.created_at).toLocaleString('fr-FR')}</time></div>`).join('') || '<p class="muted">Aucune trace.</p>'}</section></section>`;
}

async function loadApp(): Promise<void> {
  try {
    const user = await api<User>('/api/auth/me');
    if (user.role === 'DRIVER') await showDriver(user);
    else if (user.role === 'DISPATCHER') await showDispatcher(user);
    else await showAdmin(user);
    document.querySelector<HTMLButtonElement>('#logout')?.addEventListener('click', async () => { try { await api('/api/auth/logout', { method: 'POST' }); } finally { renderLogin(); } });
  } catch { renderLogin(); }
}

renderLogin();
loadApp();
