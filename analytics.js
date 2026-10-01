/* Google Analytics 4 — aucun chargement Google avant acceptation. */
(() => {
  'use strict';
  const MEASUREMENT_ID = 'G-BYF49HVYSN';
  const STORAGE_KEY = 'qvmd_analytics_consent_v1';
  const SIX_MONTHS = 180 * 24 * 60 * 60 * 1000;
  const DENIED = {
    analytics_storage: 'denied',
    ad_storage: 'denied',
    ad_user_data: 'denied',
    ad_personalization: 'denied'
  };
  const SEARCH_FIELDS = new Set(['searchInput', 'searchFilter', 'nameFilter', 'q']);
  const IS_PRODUCTION = ['quevotemondepute.fr', 'www.quevotemondepute.fr'].includes(location.hostname);
  let consent = readConsent();
  let ready = false;
  let started = false;
  let pendingSearch = null;
  let searchTimer;
  let expiryTimer;
  let fallbackTimer;
  let lastSearch = '';
  let previousFocus;

  window['ga-disable-' + MEASUREMENT_ID] = consent?.choice !== 'accepted';

  function readConsent() {
    try {
      const value = JSON.parse(localStorage.getItem(STORAGE_KEY));
      if (value && ['accepted', 'refused'].includes(value.choice) &&
          Number.isFinite(value.expires) && value.expires > Date.now()) return value;
    } catch (_) { /* La navigation reste possible si le stockage est bloqué. */ }
    return null;
  }

  function allowed() {
    return IS_PRODUCTION && consent?.choice === 'accepted' && consent.expires > Date.now();
  }

  function command() {
    window.dataLayer.push(arguments);
  }

  function pageLocation() {
    const original = new URL(location.href);
    const clean = new URL(original.pathname, original.origin);
    // Garder les identifiants publics des fiches, jamais une recherche libre dans l'URL.
    const validators = { uid: /^(?:PA\d+|VTANR\d+L\d+V\d+)$/, year: /^20\d{2}$/ };
    for (const [key, pattern] of Object.entries(validators)) {
      const value = original.searchParams.get(key);
      if (value && pattern.test(value)) clean.searchParams.set(key, value);
    }
    if (original.pathname.endsWith('/groupe.html')) {
      const group = document.getElementById('groupTitle')?.textContent.trim();
      if (group && group !== 'Chargement…') clean.searchParams.set('name', group.slice(0, 100));
    }
    return clean.href;
  }

  function referrerOrigin() {
    try { return document.referrer ? new URL(document.referrer).origin + '/' : ''; }
    catch (_) { return ''; }
  }

  function start() {
    if (!allowed() || !ready) return;
    window['ga-disable-' + MEASUREMENT_ID] = false;
    if (started) return;
    started = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = command;
    command('consent', 'default', { ...DENIED });
    command('consent', 'update', { ...DENIED, analytics_storage: 'granted' });
    command('js', new Date());
    command('config', MEASUREMENT_ID, {
      page_title: document.title,
      page_location: pageLocation(),
      page_referrer: referrerOrigin(),
      allow_google_signals: false,
      allow_ad_personalization_signals: false,
      cookie_domain: 'none',
      cookie_expires: SIX_MONTHS / 1000,
      cookie_update: false,
      cookie_flags: 'SameSite=Lax;Secure'
    });
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://www.googletagmanager.com/gtag/js?id=' + MEASUREMENT_ID;
    script.id = 'qvmd-google-tag';
    document.head.appendChild(script);
  }

  function clearAnalyticsCookies() {
    const domains = ['', location.hostname, '.' + location.hostname, 'quevotemondepute.fr', '.quevotemondepute.fr'];
    for (const cookie of document.cookie.split(';')) {
      const name = cookie.split('=')[0].trim();
      if (!/^_ga(?:_|$)/.test(name)) continue;
      for (const domain of domains) {
        document.cookie = name + '=; Max-Age=0; path=/; SameSite=Lax' + (domain ? '; domain=' + domain : '');
      }
    }
  }

  function stop() {
    window['ga-disable-' + MEASUREMENT_ID] = true;
    cancelSearch();
    lastSearch = '';
    if (started) command('consent', 'update', { ...DENIED });
    clearAnalyticsCookies();
  }

  function scheduleExpiry() {
    clearTimeout(expiryTimer);
    if (!consent) return;
    const remaining = consent.expires - Date.now();
    if (remaining <= 0) {
      consent = null;
      try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
      stop();
      showPreferences(false);
      return;
    }
    expiryTimer = setTimeout(scheduleExpiry, Math.min(remaining, 2147483647));
  }

  function choose(choice) {
    consent = { choice, expires: Date.now() + SIX_MONTHS };
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(consent)); } catch (_) {}
    if (choice === 'accepted') {
      if (started) command('consent', 'update', { ...DENIED, analytics_storage: 'granted' });
      start();
    } else stop();
    document.getElementById('qvmd-consent').hidden = true;
    document.getElementById('qvmd-cookie-settings').setAttribute('aria-expanded', 'false');
    if (previousFocus?.isConnected && previousFocus !== document.body) previousFocus.focus();
    else document.getElementById('qvmd-cookie-settings').focus();
    scheduleExpiry();
  }

  function showPreferences(focus = true) {
    const panel = document.getElementById('qvmd-consent');
    if (!panel) return;
    previousFocus = document.activeElement;
    panel.hidden = false;
    document.getElementById('qvmd-cookie-settings').setAttribute('aria-expanded', 'true');
    document.getElementById('qvmd-consent-status').textContent = consent
      ? (consent.choice === 'accepted' ? 'Votre choix actuel : statistiques acceptées.' : 'Votre choix actuel : statistiques refusées.')
      : '';
    if (focus) document.getElementById('qvmd-consent-title').focus();
  }

  function cancelSearch() {
    clearTimeout(searchTimer);
    pendingSearch = null;
  }

  function searchTerm(value) {
    const term = String(value || '').normalize('NFKC').replace(/\s+/g, ' ').trim();
    // Écarter les adresses e-mail, URL et longues suites de chiffres (ex. téléphone).
    if (term.length < 2 || term.length > 100 || /@|https?:|www\./i.test(term) ||
        (term.match(/\d/g) || []).length >= 7) return '';
    return term;
  }

  function flushSearch() {
    const item = pendingSearch;
    cancelSearch();
    if (!item || !allowed() || !started || item.key === lastSearch) return;
    lastSearch = item.key;
    const params = {
      search_term: item.term,
      results_count: item.count,
      search_area: item.area,
      page_title: document.title,
      page_location: pageLocation(),
      send_to: MEASUREMENT_ID
    };
    command('event', 'view_search_results', params);
    if (item.count === 0) command('event', 'search_no_results', { ...params });
  }

  function search(value, count, area, immediate = false) {
    cancelSearch();
    if (!allowed() || !ready || !Number.isInteger(count) || count < 0) return;
    const term = searchTerm(value);
    if (!term) { lastSearch = ''; return; }
    const key = pageLocation() + '|' + area + '|' + term.toLocaleLowerCase('fr');
    if (key === lastSearch) return;
    pendingSearch = { term, count, area, key };
    if (immediate) flushSearch();
    else searchTimer = setTimeout(flushSearch, 1500);
  }

  window.qvmdAnalytics = {
    ready() {
      clearTimeout(fallbackTimer);
      ready = true;
      start();
    },
    search,
    cancelSearch,
    showPreferences
  };

  function init() {
    const footer = document.createElement('footer');
    footer.className = 'qvmd-privacy-footer';
    footer.innerHTML = '<a href="./confidentialite.html">Confidentialité</a>' +
      '<button type="button" id="qvmd-cookie-settings" aria-controls="qvmd-consent" aria-expanded="false">Choix des cookies</button>';
    document.body.appendChild(footer);
    const panel = document.createElement('section');
    panel.id = 'qvmd-consent';
    panel.className = 'qvmd-consent';
    panel.hidden = true;
    panel.setAttribute('aria-labelledby', 'qvmd-consent-title');
    panel.innerHTML = '<div class="qvmd-consent-text">' +
      '<h2 id="qvmd-consent-title" tabindex="-1">Statistiques de fréquentation</h2>' +
      '<p>Acceptez-vous les cookies Google Analytics pour mesurer les visites, les pages consultées et les recherches effectuées sur ce site ? Votre choix est conservé pendant 6 mois et peut être modifié en bas de page.</p>' +
      '<a href="./confidentialite.html">En savoir plus</a>' +
      '<p id="qvmd-consent-status" aria-live="polite"></p></div>' +
      '<div class="qvmd-consent-actions"><button type="button" id="qvmd-consent-refuse">Refuser</button>' +
      '<button type="button" id="qvmd-consent-accept">Accepter</button>' +
      '<button type="button" id="qvmd-consent-close">Fermer</button></div>';
    document.body.appendChild(panel);
    document.getElementById('qvmd-cookie-settings').addEventListener('click', () => showPreferences());
    document.getElementById('qvmd-consent-accept').addEventListener('click', () => choose('accepted'));
    document.getElementById('qvmd-consent-refuse').addEventListener('click', () => choose('refused'));
    document.getElementById('qvmd-consent-close').addEventListener('click', () => {
      panel.hidden = true;
      document.getElementById('qvmd-cookie-settings').setAttribute('aria-expanded', 'false');
      if (previousFocus?.isConnected && previousFocus !== document.body) previousFocus.focus();
      else document.getElementById('qvmd-cookie-settings').focus();
    });
    if (!consent) { clearAnalyticsCookies(); showPreferences(false); }
    else if (consent.choice === 'refused') clearAnalyticsCookies();
    scheduleExpiry();
    // Les pages appellent ready() après avoir défini leur titre. Même une page en erreur reste mesurable.
    if (!ready) fallbackTimer = setTimeout(() => window.qvmdAnalytics.ready(), 10000);
    document.addEventListener('input', event => {
      if (SEARCH_FIELDS.has(event.target.id)) {
        cancelSearch();
        if (!event.target.value.trim()) lastSearch = '';
      }
    }, true);
    document.addEventListener('keydown', event => {
      if (event.key === 'Enter' && SEARCH_FIELDS.has(event.target.id)) flushSearch();
    });
    document.addEventListener('click', event => {
      if (event.target.closest('a[href]')) flushSearch();
    });
    document.addEventListener('visibilitychange', () => {
      scheduleExpiry();
      if (document.visibilityState === 'hidden') flushSearch();
    });
  }

  window.addEventListener('storage', event => {
    if (event.key !== STORAGE_KEY && event.key !== null) return;
    consent = readConsent();
    if (allowed()) {
      if (started) command('consent', 'update', { ...DENIED, analytics_storage: 'granted' });
      start();
    } else stop();
    const panel = document.getElementById('qvmd-consent');
    if (panel) {
      panel.hidden = !!consent;
      document.getElementById('qvmd-cookie-settings').setAttribute('aria-expanded', String(!consent));
    }
    scheduleExpiry();
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
