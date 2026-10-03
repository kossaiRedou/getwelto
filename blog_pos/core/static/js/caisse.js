/*
 * WELTO — Caisse. JavaScript sans dépendance.
 *
 * Règles de calcul : tous les montants sont des CENTIMES ENTIERS (jamais de
 * nombres à virgule). Le serveur recalcule tout à l'encaissement à partir des
 * prix en base ; le total affiché ici lui est envoyé pour contrôle.
 * Le catalogue est gardé en cache local (localStorage + ETag) : la recherche
 * et le scan restent instantanés même avec une connexion lente.
 */
(function () {
  'use strict';

  var root = document.getElementById('pos');
  if (!root) return;

  var URLS = {
    catalog: root.dataset.catalogUrl,
    checkout: root.dataset.checkoutUrl,
    clientSearch: root.dataset.clientSearchUrl,
    clientCreate: root.dataset.clientCreateUrl,
    login: root.dataset.loginUrl
  };
  var FINE_POINTER = window.WeltoKit.finePointer;
  var STORE_CATALOG = 'welto.catalog.v1';
  var STORE_CART = 'welto.cart.v1';

  var $ = function (id) { return document.getElementById(id); };
  var el = {
    search: $('search'), cats: $('cats'), results: $('results'),
    cart: $('cart'), cartEmpty: $('cart-empty'), cartCount: $('cart-count'), cartClear: $('cart-clear'),
    clientBtn: $('client-btn'), clientLabel: $('client-label'),
    discountBtn: $('discount-btn'), discountLabel: $('discount-label'), discountRow: $('discount-row'), discount: $('discount'),
    subtotal: $('subtotal'), total: $('total'), methods: $('methods'),
    amountRow: $('amount-row'), amountLabel: $('amount-label'), amount: $('amount'), quick: $('quick'), amountInfo: $('amount-info'),
    validate: $('validate'), toast: $('toast'), net: $('net-status'),
    clientModal: $('client-modal'), clientQ: $('client-q'), clientResults: $('client-results'), clientHint: $('client-hint'),
    clientRemove: $('client-remove'), clientNew: $('client-new'), clientForm: $('client-form'), clientError: $('client-error'),
    done: $('done')
  };

  // Outils partagés (kit.js) : montants en centimes, requêtes, alertes.
  var K = window.WeltoKit;
  var loadJSON = K.loadJSON, saveJSON = K.saveJSON, esc = K.esc, norm = K.norm, fmt = K.fmt,
      parseMoney = K.parseMoney, toDecimal = K.toDecimal, uuid = K.uuid, beep = K.beep;
  var toast = K.toaster(el.toast);
  function setOnline(on) { el.net.classList.toggle('hidden', on); }
  var request = K.requester({ loginUrl: URLS.login, toast: toast, onNetwork: setOnline });
  function persist() { saveJSON(STORE_CART, state); }

  // ------------------------------------------------------------------ état
  var catalog = { products: [], byId: {}, byBarcode: {}, categories: [] };
  var state = loadJSON(STORE_CART) || {};
  state.lines = state.lines || [];          // [{id, qty}]
  state.discount = state.discount || 0;     // centimes
  state.method = state.method || 'cash';
  state.amount = state.amount || '';        // saisie brute
  state.client = state.client || null;      // {id, name, phone, debt}
  state.saleKey = state.saleKey || null;
  var category = 0;
  var busy = false;
  var editingPrice = null;   // produit dont le prix est en cours de modification


  // ------------------------------------------------------------- catalogue
  function applyCatalog(data) {
    var byId = {}, byBarcode = {};
    var products = data.products.map(function (row) {
      var p = { id: row[0], title: row[1], barcode: row[2], price: row[3], stock: row[4], cat: row[5], color: K.safeColor(row[6]) };
      p.key = norm(p.title + ' ' + p.barcode);
      byId[p.id] = p;
      if (p.barcode) byBarcode[p.barcode] = p;
      return p;
    });
    catalog = { products: products, byId: byId, byBarcode: byBarcode, categories: data.categories || [] };
    // Le panier suit le catalogue : produits retirés de la vente supprimés.
    var before = state.lines.length;
    state.lines = state.lines.filter(function (l) { return byId[l.id]; });
    if (state.lines.length !== before) toast('Un produit retiré de la vente a été enlevé du panier.', 'warn');
    renderCats();
    renderResults();
    render();
  }

  function loadCatalog(force) {
    var cached = loadJSON(STORE_CATALOG);
    if (cached && !catalog.products.length) applyCatalog(cached.data);
    var headers = {};
    if (cached && cached.etag && !force) headers['If-None-Match'] = cached.etag;
    return request(URLS.catalog, { headers: headers }).then(function (r) {
      if (r.status === 304) return;
      if (!r.ok) throw new Error('catalogue');
      var etag = r.headers.get('ETag');
      return r.json().then(function (data) {
        saveJSON(STORE_CATALOG, { etag: etag, data: data });
        applyCatalog(data);
      });
    }).catch(function (err) {
      if (err && err.handled) return;
      if (!catalog.products.length) toast('Impossible de charger les produits. Vérifiez la connexion.');
    });
  }

  // ------------------------------------------------------------- recherche
  function parseQuery(raw) {
    var m = String(raw).trim().match(/^(\d{1,6})\s*[*xX×]\s*(.*)$/);
    return m ? { qty: parseInt(m[1], 10), text: m[2].trim() } : { qty: 1, text: String(raw).trim() };
  }

  function findProducts(text) {
    var tokens = norm(text).split(/\s+/).filter(Boolean);
    var list = catalog.products.filter(function (p) {
      if (category && p.cat !== category) return false;
      for (var i = 0; i < tokens.length; i++) if (p.key.indexOf(tokens[i]) === -1) return false;
      return true;
    });
    if (tokens.length) {
      var first = tokens[0];
      list.sort(function (a, b) {
        var sa = norm(a.title).indexOf(first) === 0 ? 0 : 1;
        var sb = norm(b.title).indexOf(first) === 0 ? 0 : 1;
        return sa - sb || a.title.localeCompare(b.title, 'fr');
      });
    }
    return list.slice(0, 60);
  }

  function renderCats() {
    if (!catalog.categories.length) { el.cats.innerHTML = ''; return; }
    var chip = function (id, label, color) {
      var on = category === id;
      return '<button type="button" data-cat="' + id + '" class="inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium ' +
        (on ? 'bg-brand-600 text-white' : 'bg-navy-800 text-slate-300 hover:bg-navy-700') + '">' +
        (color ? '<span class="h-2.5 w-2.5 rounded-full" style="background:' + K.safeColor(color) + '"></span>' : '') +
        esc(label) + '</button>';
    };
    var used = {};
    catalog.products.forEach(function (p) { used[p.cat] = true; });
    el.cats.innerHTML = chip(0, 'Tout') + catalog.categories.filter(function (c) { return used[c[0]]; })
      .map(function (c) { return chip(c[0], c[1], c[2]); }).join('');
  }

  var resultsList = [];
  function renderResults() {
    var q = parseQuery(el.search.value);
    resultsList = findProducts(q.text);
    if (!catalog.products.length) {
      el.results.innerHTML = '<p class="p-6 text-center text-slate-500">Aucun produit. Ajoutez vos produits dans « Produits ».</p>';
      return;
    }
    if (!resultsList.length) {
      el.results.innerHTML = '<p class="p-6 text-center text-slate-500">Aucun produit trouvé.</p>';
      return;
    }
    el.results.innerHTML = '<div class="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">' + resultsList.map(function (p) {
      var out = p.stock <= 0;
      return '<button type="button" data-add="' + p.id + '" class="flex w-full items-center gap-3 rounded-xl border-l-4 bg-navy-900 py-2.5 pl-2.5 pr-3 text-left ring-1 ring-navy-800 hover:bg-navy-800 active:bg-navy-700' + (out ? ' opacity-50' : '') + '" style="border-left-color:' + p.color + '">' +
        K.badge(p.title, p.color) + '<span class="min-w-0 flex-1"><span class="block truncate font-semibold text-white">' + esc(p.title) + '</span>' +
        '<span class="block text-xs ' + (out ? 'text-rose-400' : 'text-slate-400') + '">' + (out ? 'Rupture de stock' : 'Stock : ' + p.stock) + '</span></span>' +
        '<span class="shrink-0 font-bold tabular-nums text-brand-300">' + fmt(p.price) + '</span></button>';
    }).join('') + '</div>';
  }

  function setSearching() {
    root.classList.toggle('searching', el.search.value.trim() !== '');
  }

  // --------------------------------------------------------------- panier
  function line(id) {
    for (var i = 0; i < state.lines.length; i++) if (state.lines[i].id === id) return state.lines[i];
    return null;
  }
  function changed() {
    state.saleKey = null;   // le contenu a changé : ce sera une nouvelle vente
    if (!state.lines.length) {
      // Panier vide : on repart d'un encaissement neuf.
      state.amount = '';
      state.discount = 0;
      state.method = 'cash';
      el.discount.value = '';
      el.amount.value = '';
    }
    persist();
    render();
  }

  function addProduct(p, qty) {
    if (p.stock <= 0) { beep(false); toast('« ' + p.title + ' » est en rupture de stock.'); return false; }
    var l = line(p.id);
    var wanted = (l ? l.qty : 0) + qty;
    if (wanted > p.stock) {
      wanted = p.stock;
      toast('Stock disponible pour « ' + p.title + ' » : ' + p.stock, 'warn');
    }
    if (l) l.qty = wanted; else state.lines.push({ id: p.id, qty: wanted });
    beep(true);
    changed();
    flash(p.id);
    return true;
  }

  function setQty(id, qty) {
    var p = catalog.byId[id], l = line(id);
    if (!p || !l) return;
    if (!(qty >= 1)) qty = 1;
    if (qty > p.stock) { qty = p.stock; toast('Stock disponible pour « ' + p.title + ' » : ' + p.stock, 'warn'); }
    l.qty = qty;
    changed();
  }

  function removeLine(id) {
    state.lines = state.lines.filter(function (l) { return l.id !== id; });
    changed();
  }

  function flash(id) {
    var node = el.cart.querySelector('[data-line="' + id + '"]');
    if (!node) return;
    node.classList.add('ring-2', 'ring-brand-400');
    node.scrollIntoView({ block: 'nearest' });
    setTimeout(function () { node.classList.remove('ring-2', 'ring-brand-400'); }, 500);
  }

  // Prix unitaire de la ligne : prix négocié pour cette vente, sinon prix catalogue.
  function unitPrice(l, p) { return l.price != null ? l.price : p.price; }

  function totals() {
    var subtotal = 0, count = 0;
    state.lines.forEach(function (l) {
      var p = catalog.byId[l.id];
      if (p) { subtotal += unitPrice(l, p) * l.qty; count += l.qty; }
    });
    var discount = Math.min(state.discount, subtotal);
    return { subtotal: subtotal, discount: discount, total: subtotal - discount, count: count };
  }

  var ICON = {
    minus: '<svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M5 12h14"/></svg>',
    plus: '<svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M5 12h14M12 5v14"/></svg>',
    trash: '<svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>'
  };

  function renderCart() {
    var t = totals();
    el.cartEmpty.hidden = state.lines.length > 0;
    el.cartEmpty.style.display = state.lines.length ? 'none' : '';
    el.cart.hidden = !state.lines.length;
    el.cartClear.classList.toggle('hidden', !state.lines.length);
    el.cartCount.textContent = t.count ? '(' + t.count + ' article' + (t.count > 1 ? 's' : '') + ')' : '';

    var active = document.activeElement && document.activeElement.dataset;
    if (active && (active.qty || active.priceInput)) return;  // ne pas réécrire une saisie en cours
    el.cart.innerHTML = state.lines.map(function (l) {
      var p = catalog.byId[l.id];
      if (!p) return '';
      var unit = unitPrice(l, p);
      var priceHtml;
      if (editingPrice === p.id) {
        priceHtml = '<span class="mt-1 flex items-center gap-2">' +
          '<input data-price-input="' + p.id + '" value="' + K.toInput(unit) + '" inputmode="decimal" aria-label="Prix pour cette vente" ' +
          'class="h-9 w-32 rounded-lg border-2 border-brand-400 bg-navy-950 px-2 text-right font-bold text-white focus:outline-none">' +
          '<span class="text-xs text-slate-400">pour cette vente</span></span>';
      } else {
        priceHtml = '<span class="mt-0.5 flex flex-wrap items-center gap-x-2 text-sm">' +
          (l.price != null ? '<span class="text-slate-500 line-through">' + fmt(p.price) + '</span>' : '') +
          '<button type="button" data-price="' + p.id + '" class="-ml-1.5 rounded-md px-1.5 py-1 font-semibold underline decoration-dotted underline-offset-2 hover:bg-navy-700 ' +
          (l.price != null ? 'text-brand-300' : 'text-slate-300') + '" title="Modifier le prix pour cette vente">' + fmt(unit) + ' ✎</button>' +
          '<span class="text-slate-400">× ' + l.qty + '</span>' +
          (l.price != null ? '<button type="button" data-reset-price="' + p.id + '" class="rounded-md px-1.5 py-0.5 text-slate-400 hover:bg-navy-700 hover:text-white">↺ prix normal</button>' : '') +
          '</span>';
      }
      return '<li data-line="' + p.id + '" class="rounded-xl border-l-4 bg-navy-800 p-3 transition' + (l.price != null ? ' ring-1 ring-brand-400/50' : '') + '" style="border-left-color:' + p.color + '">' +
        '<div class="flex items-start gap-3">' + K.badge(p.title, p.color, 'h-9 w-9 text-xs') + '<div class="min-w-0 flex-1">' +
        '<p class="truncate font-semibold text-white">' + esc(p.title) + '</p>' + priceHtml + '</div>' +
        '<p class="shrink-0 text-lg font-bold tabular-nums text-white">' + fmt(unit * l.qty) + '</p></div>' +
        '<div class="mt-2 flex items-center gap-2">' +
        '<button type="button" class="step" data-dec="' + p.id + '" aria-label="Moins">' + ICON.minus + '</button>' +
        '<input data-qty="' + p.id + '" value="' + l.qty + '" inputmode="numeric" pattern="[0-9]*" aria-label="Quantité" ' +
        'class="h-10 w-20 rounded-lg border border-navy-600 bg-navy-950 text-center text-lg font-bold text-white focus:border-brand-400 focus:outline-none">' +
        '<button type="button" class="step" data-inc="' + p.id + '" aria-label="Plus">' + ICON.plus + '</button>' +
        '<span class="text-xs text-slate-500">/ ' + p.stock + '</span>' +
        '<button type="button" data-del="' + p.id + '" class="ml-auto grid h-10 w-10 place-items-center rounded-lg text-slate-400 hover:bg-rose-600 hover:text-white" aria-label="Retirer">' + ICON.trash + '</button>' +
        '</div></li>';
    }).join('');
  }

  // --------------------------------------------------------- encaissement
  function quickAmounts(total) {
    if (total <= 0) return [];
    var units = total / 100;
    var steps = units >= 10000 ? [1000, 5000, 10000] : units >= 1000 ? [500, 1000, 5000] : units >= 100 ? [50, 100, 500] : [5, 10, 50];
    var out = [total];
    steps.forEach(function (s) {
      var c = Math.ceil(units / s) * s * 100;
      if (out.indexOf(c) === -1) out.push(c);
    });
    return out.slice(0, 4);
  }

  function renderPayment() {
    var t = totals();
    el.total.textContent = fmt(t.total);
    el.subtotal.hidden = !t.discount;
    el.subtotal.textContent = fmt(t.subtotal);
    el.discountLabel.textContent = t.discount ? '− ' + fmt(t.discount) : 'Remise';
    el.discountBtn.classList.toggle('text-brand-300', !!t.discount);

    var c = state.client;
    el.clientLabel.textContent = c ? c.name + (c.debt ? ' · doit ' + fmt(c.debt) : '') : 'Ajouter un client (facultatif)';
    el.clientBtn.classList.toggle('border-brand-400', !!c);

    Array.prototype.forEach.call(el.methods.querySelectorAll('[data-method]'), function (b) {
      b.classList.toggle('selected', b.dataset.method === state.method);
    });

    var showAmount = state.method === 'cash' || state.method === 'credit';
    el.amountRow.hidden = !showAmount;
    el.amountLabel.textContent = state.method === 'credit' ? 'Acompte' : 'Montant reçu';
    el.amount.placeholder = state.method === 'credit' ? '0' : fmt(t.total);
    if (document.activeElement !== el.amount) el.amount.value = state.amount;

    el.quick.innerHTML = state.method === 'cash' ? quickAmounts(t.total).map(function (c, i) {
      return '<button type="button" class="qbtn" data-quick="' + c + '">' + (i === 0 ? 'Exact' : fmt(c)) + '</button>';
    }).join('') : '';

    var info = '', cls = 'text-slate-400';
    var amount = parseMoney(state.amount);
    if (isNaN(amount)) {
      info = 'Montant invalide'; cls = 'text-rose-400';
    } else if (state.method === 'cash' && amount !== null && t.total > 0) {
      if (amount > t.total) { info = 'Monnaie à rendre : ' + fmt(amount - t.total); cls = 'text-emerald-400 text-base'; }
      else if (amount < t.total) { info = 'Reste à payer : ' + fmt(t.total - amount) + ' (crédit client)'; cls = 'text-amber-300'; }
    } else if (state.method === 'credit' && t.total > 0) {
      var rest = t.total - Math.min(amount || 0, t.total);
      info = 'Reste dû par le client : ' + fmt(rest); cls = 'text-amber-300';
    }
    el.amountInfo.textContent = info;
    el.amountInfo.className = 'min-h-5 text-right text-sm font-semibold ' + cls;

    el.validate.disabled = busy || !state.lines.length || isNaN(amount);
    el.validate.textContent = busy ? 'Enregistrement…' : 'VALIDER LA VENTE';
  }

  function render() {
    renderCart();
    renderPayment();
  }

  function checkout() {
    if (busy || !state.lines.length) return;
    var t = totals();
    var amount = parseMoney(state.amount);
    if (isNaN(amount)) { toast('Montant reçu invalide.'); el.amount.focus(); return; }
    var unpaid = state.method === 'credit' || (state.method === 'cash' && amount !== null && amount < t.total);
    if (unpaid && !state.client) {
      openClient('Paiement incomplet : choisissez le client à qui inscrire le reste dû.');
      return;
    }
    if (!state.saleKey) { state.saleKey = uuid(); persist(); }

    busy = true;
    renderPayment();
    request(URLS.checkout, {
      timeout: 45000,
      body: {
        lines: state.lines.map(function (l) {
          return { product_id: l.id, qty: l.qty, price: l.price != null ? toDecimal(l.price) : null };
        }),
        method: state.method,
        amount: amount === null ? null : toDecimal(amount),
        discount: toDecimal(t.discount),
        client_id: state.client ? state.client.id : null,
        expected_total: toDecimal(t.total),
        sale_key: state.saleKey
      }
    }).then(function (r) {
      return r.json().then(function (data) { return { status: r.status, data: data }; });
    }).then(function (res) {
      busy = false;
      var data = res.data;
      if (data.ok) return saleDone(data.order, data.replayed);
      beep(false);
      toast(data.error || 'Vente refusée.');
      if (data.code === 'client_required') openClient(data.error);
      if (data.code === 'stock' && data.data && data.data.shortages) {
        data.data.shortages.forEach(function (s) { if (catalog.byId[s.product_id]) catalog.byId[s.product_id].stock = s.available; });
        loadCatalog(true);
      }
      if (data.code === 'price_changed') loadCatalog(true);
      render();
    }).catch(function (err) {
      busy = false;
      render();
      if (err && err.handled) return;
      beep(false);
      toast("Connexion lente ou coupée : la vente n'est pas confirmée. Appuyez à nouveau sur Valider — elle ne sera jamais enregistrée deux fois.");
    });
  }

  function saleDone(order, replayed) {
    // Stock local mis à jour tout de suite, puis catalogue resynchronisé.
    state.lines.forEach(function (l) {
      var p = catalog.byId[l.id];
      if (p && !replayed) p.stock = Math.max(0, p.stock - l.qty);
    });
    state.lines = [];
    state.discount = 0;
    state.amount = '';
    state.method = 'cash';
    state.client = null;
    state.saleKey = null;
    persist();
    el.discount.value = '';
    el.discountRow.hidden = true;
    render();
    renderResults();
    loadCatalog();

    $('done-number').textContent = order.number;
    $('done-total').textContent = fmt(order.total);
    var change = $('done-change');
    change.hidden = !order.change;
    change.querySelector('span').textContent = fmt(order.change);
    var debt = $('done-debt');
    debt.hidden = !order.remaining;
    debt.textContent = order.remaining ? 'Reste dû par ' + order.client + ' : ' + fmt(order.remaining) : '';
    $('done-ticket').href = order.ticket_url + '?print=1';
    $('done-detail').href = order.detail_url;
    el.done.hidden = false;
    $('done-new').focus();
  }

  function closeDone() {
    el.done.hidden = true;
    el.search.value = '';
    setSearching();
    renderResults();
    if (FINE_POINTER) el.search.focus();
  }

  // ---------------------------------------------------------------- client
  var clientTimer;
  function openClient(hint) {
    el.clientHint.hidden = !hint;
    el.clientHint.textContent = hint || '';
    el.clientRemove.hidden = !state.client;
    el.clientError.textContent = '';
    el.clientResults.innerHTML = '';
    el.clientQ.value = '';
    el.clientModal.hidden = false;
    el.clientQ.focus();
  }
  function closeClient() { el.clientModal.hidden = true; }
  function chooseClient(c) {
    state.client = c;
    changed();
    closeClient();
    toast('Client : ' + c.name, 'ok');
  }

  function searchClients() {
    var q = el.clientQ.value.trim();
    if (q.length < 2) { el.clientResults.innerHTML = ''; return; }
    request(URLS.clientSearch + '?q=' + encodeURIComponent(q)).then(function (r) { return r.json(); }).then(function (data) {
      if (el.clientQ.value.trim() !== q) return;
      clientCache = {};
      el.clientResults.innerHTML = data.clients.length ? data.clients.map(function (c) {
        clientCache[c.id] = c;
        return '<button type="button" data-client="' + c.id + '" class="flex w-full items-center gap-3 py-3 text-left hover:bg-slate-50">' +
          '<span class="min-w-0 flex-1"><span class="block truncate font-semibold">' + esc(c.name) + '</span>' +
          '<span class="block text-sm text-slate-500">' + esc(c.phone) + '</span></span>' +
          (c.debt ? '<span class="badge badge-red">doit ' + fmt(c.debt) + '</span>' : '') + '</button>';
      }).join('') : '<p class="py-3 text-sm text-slate-500">Aucun client trouvé.</p>';
    }).catch(function () { el.clientResults.innerHTML = '<p class="py-3 text-sm text-rose-600">Recherche impossible (connexion).</p>'; });
  }
  var clientCache = {};

  // ------------------------------------------------------------ événements
  // Rendu immédiat (pas de délai) : la liste affichée correspond toujours à la
  // saisie, un tap rapide ne peut pas ajouter un produit d'une liste périmée.
  el.search.addEventListener('input', function () {
    setSearching();
    renderResults();
  });
  el.search.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { el.search.value = ''; setSearching(); renderResults(); return; }
    if (e.key !== 'Enter') return;
    e.preventDefault();
    var q = parseQuery(el.search.value);
    if (!q.text) return;
    var p = catalog.byBarcode[q.text];
    if (!p) {
      var list = findProducts(q.text);
      var exact = list.filter(function (x) { return norm(x.title) === norm(q.text); });
      p = exact.length === 1 ? exact[0] : list.length === 1 ? list[0] : null;
      if (!p) {
        if (!list.length) { beep(false); toast('Produit ou code-barres inconnu : ' + q.text); }
        return;
      }
    }
    if (addProduct(p, q.qty)) {
      el.search.value = '';
      setSearching();
      renderResults();
    }
  });

  // Scan avec l'appareil photo (dépannage quand il n'y a pas de douchette).
  var cameraBtn = $('camera');
  if (cameraBtn && window.WeltoScanner && window.WeltoScanner.supported()) {
    cameraBtn.hidden = false;
    cameraBtn.addEventListener('click', function () {
      window.WeltoScanner.open({
        zxingUrl: root.dataset.zxingUrl,
        title: 'Caisse : scanner les produits',
        onCode: function (code) {
          var p = catalog.byBarcode[code];
          if (!p) { beep(false); return 'Code inconnu : ' + code; }
          if (!addProduct(p, 1)) return '« ' + p.title + ' » : stock épuisé';
          return 'Ajouté : ' + p.title + ' (×' + line(p.id).qty + ')';
        }
      });
    });
  }

  el.results.addEventListener('click', function (e) {
    var b = e.target.closest('[data-add]');
    if (!b) return;
    var p = catalog.byId[b.dataset.add];
    if (p && addProduct(p, parseQuery(el.search.value).qty)) {
      el.search.value = '';
      setSearching();
      renderResults();
      if (FINE_POINTER) el.search.focus();
    }
  });

  el.cats.addEventListener('click', function (e) {
    var b = e.target.closest('[data-cat]');
    if (!b) return;
    category = parseInt(b.dataset.cat, 10);
    renderCats();
    renderResults();
  });

  // Prix négocié : ne concerne que cette vente, la fiche produit ne change pas.
  function applyPrice(id, raw) {
    var l = line(id), p = catalog.byId[id];
    editingPrice = null;
    if (!l || !p) return render();
    var cents = parseMoney(raw);
    if (cents === null || cents === p.price) {
      delete l.price;
    } else if (isNaN(cents) || cents <= 0) {
      toast('Prix invalide : il doit être supérieur à 0.');
    } else {
      l.price = cents;
    }
    changed();
  }

  el.cart.addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.inc) { var l1 = line(+b.dataset.inc); setQty(+b.dataset.inc, l1.qty + 1); }
    else if (b.dataset.dec) { var l2 = line(+b.dataset.dec); if (l2.qty > 1) setQty(+b.dataset.dec, l2.qty - 1); }
    else if (b.dataset.del) removeLine(+b.dataset.del);
    else if (b.dataset.price) {
      editingPrice = +b.dataset.price;
      render();
      var input = el.cart.querySelector('[data-price-input="' + editingPrice + '"]');
      if (input) { input.focus(); input.select(); }
    } else if (b.dataset.resetPrice) {
      delete line(+b.dataset.resetPrice).price;
      changed();
    }
  });
  el.cart.addEventListener('focusin', function (e) {
    if (e.target.dataset.qty) e.target.select();
  });
  el.cart.addEventListener('keydown', function (e) {
    if ((e.target.dataset.qty || e.target.dataset.priceInput) && e.key === 'Enter') e.target.blur();
    if (e.target.dataset.priceInput && e.key === 'Escape') { editingPrice = null; e.target.blur(); }
  });
  el.cart.addEventListener('focusout', function (e) {
    var target = e.target;
    if (target.dataset.priceInput) {
      var pid = +target.dataset.priceInput;
      if (editingPrice === null) { setTimeout(render, 0); return; }   // Échap : annulé
      setTimeout(function () { applyPrice(pid, target.value); }, 0);
      return;
    }
    if (!target.dataset.qty) return;
    var qty = parseInt(target.value.replace(/\D/g, ''), 10);
    var id = +target.dataset.qty;
    setTimeout(function () { setQty(id, qty); }, 0);
  });

  el.cartClear.addEventListener('click', function () {
    if (!window.confirm('Vider le panier ?')) return;
    state.lines = [];
    state.discount = 0;
    el.discount.value = '';
    changed();
  });

  el.discountBtn.addEventListener('click', function () {
    el.discountRow.hidden = !el.discountRow.hidden;
    if (!el.discountRow.hidden) el.discount.focus();
  });
  el.discount.addEventListener('input', function () {
    var cents = parseMoney(el.discount.value);
    var sub = totals().subtotal;
    var bad = isNaN(cents) || (cents || 0) > sub;
    el.discount.classList.toggle('border-rose-500', bad);
    state.discount = bad ? 0 : (cents || 0);
    changed();
  });

  el.methods.addEventListener('click', function (e) {
    var b = e.target.closest('[data-method]');
    if (!b) return;
    state.method = b.dataset.method;
    state.amount = '';
    changed();
    if (state.method === 'credit' && !state.client) openClient('Vente à crédit : choisissez le client.');
  });
  el.amount.addEventListener('input', function () {
    state.amount = el.amount.value;
    changed();
  });
  el.amount.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); checkout(); }
  });
  el.quick.addEventListener('click', function (e) {
    var b = e.target.closest('[data-quick]');
    if (!b) return;
    state.amount = toDecimal(+b.dataset.quick).replace('.00', '');
    el.amount.value = state.amount;
    changed();
  });

  el.validate.addEventListener('click', checkout);

  el.clientBtn.addEventListener('click', function () { openClient(); });
  el.clientModal.addEventListener('click', function (e) {
    if (e.target === el.clientModal || e.target.closest('[data-close]')) return closeClient();
    var b = e.target.closest('[data-client]');
    if (b && clientCache[b.dataset.client]) chooseClient(clientCache[b.dataset.client]);
  });
  el.clientQ.addEventListener('input', function () {
    clearTimeout(clientTimer);
    clientTimer = setTimeout(searchClients, 300);
  });
  el.clientRemove.addEventListener('click', function () {
    state.client = null;
    changed();
    closeClient();
  });
  el.clientForm.addEventListener('submit', function (e) {
    e.preventDefault();
    var form = el.clientForm;
    var button = form.querySelector('button');
    button.disabled = true;
    el.clientError.textContent = '';
    request(URLS.clientCreate, { body: { name: form.name.value, phone: form.phone.value } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        button.disabled = false;
        if (!data.ok) { el.clientError.textContent = data.error; return; }
        form.reset();
        el.clientNew.open = false;
        chooseClient(data.client);
      })
      .catch(function () { button.disabled = false; el.clientError.textContent = 'Connexion impossible, réessayez.'; });
  });

  $('done-new').addEventListener('click', closeDone);
  el.done.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeDone(); });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'F2') { e.preventDefault(); el.search.focus(); }
    if (e.key === 'F9' || (e.ctrlKey && e.key === 'Enter')) { e.preventDefault(); checkout(); }
    if (e.key === 'Escape' && !el.clientModal.hidden) closeClient();
  });
  window.addEventListener('online', function () { setOnline(true); loadCatalog(); });
  window.addEventListener('offline', function () { setOnline(false); });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) loadCatalog(); });

  // ------------------------------------------------------------- démarrage
  if (state.discount) { el.discount.value = toDecimal(state.discount).replace('.00', ''); el.discountRow.hidden = false; }
  render();
  loadCatalog();
  if (FINE_POINTER) el.search.focus();
})();
