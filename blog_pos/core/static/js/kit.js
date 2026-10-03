/*
 * WELTO — boîte à outils partagée par la caisse et la réception. Sans dépendance.
 *
 * Règle d'or : les montants sont des CENTIMES ENTIERS, jamais des nombres à
 * virgule. Ils partent vers le serveur sous forme de texte (« 38000.00 »).
 */
(function () {
  'use strict';

  function loadJSON(key) {
    try { return JSON.parse(localStorage.getItem(key)); } catch (e) { return null; }
  }
  function saveJSON(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* stockage plein */ }
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function norm(s) {
    return String(s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  }
  // 3800000 → « 38 000 » ; 125050 → « 1 250,50 »
  function fmt(cents) {
    var neg = cents < 0;
    cents = Math.abs(cents);
    var units = Math.floor(cents / 100);
    var rest = cents % 100;
    var s = String(units).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    if (rest) s += ',' + (rest < 10 ? '0' : '') + rest;
    return (neg ? '-' : '') + s;
  }
  // « 38 000 », « 1250,5 » → centimes ; '' → null ; saisie invalide → NaN
  function parseMoney(str) {
    str = String(str == null ? '' : str).replace(/[\s  ]/g, '');
    if (!str) return null;
    var m = str.match(/^(\d{1,15})(?:[.,](\d{0,2}))?$/);
    if (!m) return NaN;
    var dec = (m[2] || '') + '00';
    return parseInt(m[1], 10) * 100 + parseInt(dec.slice(0, 2), 10);
  }
  // centimes → « 38000.00 » pour le serveur
  function toDecimal(cents) {
    var rest = cents % 100;
    return Math.floor(cents / 100) + '.' + (rest < 10 ? '0' : '') + rest;
  }
  // centimes → texte modifiable dans un champ (« 38000 », « 1250.5 »)
  function toInput(cents) {
    return toDecimal(cents).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1');
  }
  // « Coca-Cola 1L » → « CC » (même règle que product.models.initials)
  function initials(title) {
    var words = String(title || '').split(/[\s\-_\/.,]+/).filter(Boolean);
    return (words.slice(0, 2).map(function (w) { return w.charAt(0); }).join('') || '?').toUpperCase();
  }
  // N'accepte qu'une couleur « #rrggbb » (protège l'attribut style).
  function safeColor(c) { return /^#[0-9a-fA-F]{6}$/.test(c || '') ? c : '#64748b'; }
  // Teinte éclaircie pour écrire un nom sur fond sombre (contraste suffisant pour toutes les couleurs).
  function textOnDark(color) {
    var c = safeColor(color), mix = 0.45, out = '#';
    for (var i = 1; i < 7; i += 2) {
      var v = parseInt(c.substr(i, 2), 16);
      out += ('0' + Math.round(v + (255 - v) * mix).toString(16)).slice(-2);
    }
    return out;
  }
  function badge(title, color, cls) {
    return '<span class="grid shrink-0 place-items-center rounded-lg font-black text-white ' + (cls || 'h-10 w-10 text-sm') +
      '" style="background:' + safeColor(color) + '" aria-hidden="true">' + esc(initials(title)) + '</span>';
  }

  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    var b = new Uint8Array(16);
    crypto.getRandomValues(b);
    b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
    var h = Array.prototype.map.call(b, function (x) { return (x + 256).toString(16).slice(1); }).join('');
    return h.slice(0, 8) + '-' + h.slice(8, 12) + '-' + h.slice(12, 16) + '-' + h.slice(16, 20) + '-' + h.slice(20);
  }
  function beep(ok) {
    try {
      var ctx = beep.ctx || (beep.ctx = new (window.AudioContext || window.webkitAudioContext)());
      var o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = ok ? 1200 : 300;
      g.gain.value = 0.05;
      o.connect(g); g.connect(ctx.destination);
      o.start(); o.stop(ctx.currentTime + (ok ? 0.06 : 0.25));
    } catch (e) { /* pas de son */ }
  }

  function toaster(node) {
    var timer;
    return function toast(message, kind) {
      var colors = kind === 'ok' ? 'bg-emerald-600 text-white' : kind === 'warn' ? 'bg-amber-400 text-navy-950' : 'bg-rose-600 text-white';
      node.className = 'fixed inset-x-3 top-16 z-[60] mx-auto max-w-md rounded-xl px-4 py-3 text-sm font-semibold shadow-xl lg:top-4 ' + colors;
      node.textContent = message;
      node.hidden = false;
      clearTimeout(timer);
      timer = setTimeout(function () { node.hidden = true; }, kind === 'ok' ? 2500 : 6000);
    };
  }

  // fetch avec délai maximal, jeton CSRF et gestion de la session expirée (401).
  function requester(opts) {
    var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    var onNetwork = opts.onNetwork || function () {};
    return function request(url, options) {
      options = options || {};
      var controller = window.AbortController ? new AbortController() : null;
      var timer = controller && setTimeout(function () { controller.abort(); }, options.timeout || 30000);
      var headers = options.headers || {};
      headers['X-Requested-With'] = 'XMLHttpRequest';
      if (options.body) {
        headers['Content-Type'] = 'application/json';
        headers['X-CSRFToken'] = csrf;
      }
      return fetch(url, {
        method: options.body ? 'POST' : 'GET',
        headers: headers,
        body: options.body ? JSON.stringify(options.body) : undefined,
        credentials: 'same-origin',
        signal: controller ? controller.signal : undefined
      }).then(function (r) {
        clearTimeout(timer);
        onNetwork(true);
        if (r.status === 401) {
          opts.toast('Session expirée : reconnexion…');
          setTimeout(function () { location.href = opts.loginUrl + '?next=' + encodeURIComponent(location.pathname); }, 1500);
          throw { handled: true };
        }
        return r;
      }, function (err) {
        clearTimeout(timer);
        onNetwork(false);
        throw err;
      });
    };
  }

  window.WeltoKit = {
    loadJSON: loadJSON, saveJSON: saveJSON, esc: esc, norm: norm, fmt: fmt, parseMoney: parseMoney,
    toDecimal: toDecimal, toInput: toInput, uuid: uuid, initials: initials, safeColor: safeColor, badge: badge, textOnDark: textOnDark, beep: beep, toaster: toaster, requester: requester,
    finePointer: !!(window.matchMedia && window.matchMedia('(pointer: fine)').matches)
  };
})();
