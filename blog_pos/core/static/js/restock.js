/*
 * WELTO — Approvisionnement (réception de marchandises). Sans dépendance.
 *
 * Même principe que la caisse : on scanne, on ajuste (quantité reçue, prix
 * d'achat, prix de vente), on valide. Un produit inconnu se crée sur place.
 * Tout est enregistré en une seule opération côté serveur (tout ou rien),
 * et une réception renvoyée deux fois n'est comptée qu'une fois.
 */
(function () {
  'use strict';

  var root = document.getElementById('restock');
  if (!root) return;

  var K = window.WeltoKit;
  var esc = K.esc, norm = K.norm, fmt = K.fmt, parseMoney = K.parseMoney, toDecimal = K.toDecimal, toInput = K.toInput;
  var STORE_CATALOG = 'welto.stockcatalog.v1';
  var STORE_DRAFT = 'welto.restock.v1';
  var $ = function (id) { return document.getElementById(id); };
  var el = {
    search: $('search'), results: $('results'), lines: $('lines'), empty: $('empty'), count: $('count'), clear: $('clear'),
    fournisseur: $('fournisseur'), reference: $('reference'), total: $('total'), validate: $('validate'),
    toast: $('toast'), net: $('net-status'), done: $('done'),
    modal: $('new-modal'), form: $('new-form'), hint: $('new-hint'), error: $('new-error'), margin: $('new-margin'),
    linkBox: $('link-box'), linkQ: $('link-q'), linkResults: $('link-results')
  };
  var toast = K.toaster(el.toast);
  function setOnline(on) { el.net.classList.toggle('hidden', on); }
  var request = K.requester({ loginUrl: root.dataset.loginUrl, toast: toast, onNetwork: setOnline });

  // ------------------------------------------------------------------ état
  var catalog = { products: [], byId: {}, byBarcode: {} };
  var draft = K.loadJSON(STORE_DRAFT) || {};
  draft.lines = draft.lines || [];   // [{uid, id, newp, qty, cost, price, barcode}] — cost/price : saisie brute
  draft.fournisseur = draft.fournisseur || '';
  draft.reference = draft.reference || '';
  draft.key = draft.key || null;
  var busy = false;
  var pendingBarcode = '';

  function persist() { K.saveJSON(STORE_DRAFT, draft); }
  function changed() {
    draft.key = null;   // contenu modifié : ce sera une nouvelle réception
    persist();
    render();
  }

  // ------------------------------------------------------------- catalogue
  function applyCatalog(data) {
    var byId = {}, byBarcode = {};
    var products = data.products.map(function (r) {
      var p = { id: r[0], title: r[1], barcode: r[2], price: r[3], stock: r[4], cat: r[5], cost: r[6], active: !!r[7], promo: r[8] };
      p.key = norm(p.title + ' ' + p.barcode);
      byId[p.id] = p;
      if (p.barcode) byBarcode[p.barcode] = p;
      return p;
    });
    catalog = { products: products, byId: byId, byBarcode: byBarcode };
    var before = draft.lines.length;
    draft.lines = draft.lines.filter(function (l) { return !l.id || byId[l.id]; });
    if (draft.lines.length !== before) { toast('Un produit supprimé a été retiré de la réception.', 'warn'); persist(); }
    renderResults();
    render();
  }

  function loadCatalog(force) {
    var cached = K.loadJSON(STORE_CATALOG);
    if (cached && !catalog.products.length) applyCatalog(cached.data);
    var headers = {};
    if (cached && cached.etag && !force) headers['If-None-Match'] = cached.etag;
    return request(root.dataset.catalogUrl, { headers: headers }).then(function (r) {
      if (r.status === 304) return;
      if (!r.ok) throw new Error('catalogue');
      var etag = r.headers.get('ETag');
      return r.json().then(function (data) {
        K.saveJSON(STORE_CATALOG, { etag: etag, data: data });
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
  function findProducts(text, limit) {
    var tokens = norm(text).split(/\s+/).filter(Boolean);
    var list = catalog.products.filter(function (p) {
      for (var i = 0; i < tokens.length; i++) if (p.key.indexOf(tokens[i]) === -1) return false;
      return true;
    });
    if (tokens.length) {
      list.sort(function (a, b) {
        var sa = norm(a.title).indexOf(tokens[0]) === 0 ? 0 : 1;
        var sb = norm(b.title).indexOf(tokens[0]) === 0 ? 0 : 1;
        return sa - sb || a.title.localeCompare(b.title, 'fr');
      });
    }
    return list.slice(0, limit || 60);
  }
  function exactTitle(title) {
    var t = norm(title.trim());
    for (var i = 0; i < catalog.products.length; i++) if (norm(catalog.products[i].title) === t) return catalog.products[i];
    return null;
  }
  function looksLikeBarcode(text) { return /^\d{6,}$/.test(text); }

  function renderResults() {
    var q = parseQuery(el.search.value);
    var list = findProducts(q.text);
    var html = '';
    if (list.length) {
      html += '<div class="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">' + list.map(function (p) {
        return '<button type="button" data-add="' + p.id + '" class="flex w-full items-center gap-3 rounded-xl bg-navy-900 px-3 py-3 text-left ring-1 ring-navy-800 hover:bg-navy-800 active:bg-navy-700">' +
          '<span class="min-w-0 flex-1"><span class="block truncate font-semibold text-white">' + esc(p.title) +
          (p.active ? '' : ' <span class="rounded bg-slate-600 px-1.5 text-[10px] font-semibold uppercase text-slate-200">retiré</span>') + '</span>' +
          '<span class="block text-xs ' + (p.stock > 0 ? 'text-slate-400' : 'text-rose-400') + '">Stock : ' + p.stock +
          (p.cost ? ' · achat ' + fmt(p.cost) : ' · prix d\'achat ?') + '</span></span>' +
          '<span class="shrink-0 font-bold tabular-nums text-brand-300">' + fmt(p.price) + '</span></button>';
      }).join('') + '</div>';
    } else if (q.text) {
      html += '<p class="p-4 text-center text-slate-500">Aucun produit ne correspond.</p>';
    } else if (!catalog.products.length) {
      html += '<p class="p-6 text-center text-slate-500">Aucun produit pour l\'instant : scannez ou tapez un nom pour créer le premier.</p>';
    }
    if (q.text && !exactTitle(q.text) && !catalog.byBarcode[q.text]) {
      html += '<button type="button" data-create class="mt-2 flex w-full items-center justify-center gap-2 rounded-xl border-2 border-dashed border-brand-400/60 px-3 py-3.5 font-semibold text-brand-200 hover:bg-brand-500/10">' +
        '+ Créer ' + (looksLikeBarcode(q.text) ? 'un produit avec le code ' : '« ') + esc(q.text) + (looksLikeBarcode(q.text) ? '' : ' »') + '</button>';
    }
    el.results.innerHTML = html;
  }
  function setSearching() { root.classList.toggle('searching', el.search.value.trim() !== ''); }
  function resetSearch() {
    el.search.value = '';
    setSearching();
    renderResults();
    if (K.finePointer) el.search.focus();
  }

  // ----------------------------------------------------------------- lignes
  function findLine(id) {
    for (var i = 0; i < draft.lines.length; i++) if (draft.lines[i].id === id) return draft.lines[i];
    return null;
  }
  function lineTitle(l) { return l.id ? catalog.byId[l.id].title : l.newp.title; }

  function addExisting(p, qty, barcode) {
    var l = findLine(p.id);
    if (l) {
      l.qty += qty;
    } else {
      l = { uid: K.uuid(), id: p.id, newp: null, qty: qty,
            cost: p.cost ? toInput(p.cost) : '', price: toInput(p.price), barcode: '' };
      draft.lines.unshift(l);
    }
    if (barcode) l.barcode = barcode;
    K.beep(true);
    changed();
    flash(l.uid);
  }

  function lineCalc(l) {
    var cost = parseMoney(l.cost), price = parseMoney(l.price);
    var p = l.id ? catalog.byId[l.id] : null;
    return {
      cost: cost, price: price,
      costOk: cost !== null && !isNaN(cost),
      priceOk: price !== null && !isNaN(price) && price > 0 && !(p && p.promo && price <= p.promo),
      total: (cost !== null && !isNaN(cost)) ? cost * l.qty : 0
    };
  }

  function totals() {
    var total = 0, units = 0, invalid = 0;
    draft.lines.forEach(function (l) {
      var c = lineCalc(l);
      total += c.total;
      units += l.qty;
      if (!c.costOk || !c.priceOk) invalid++;
    });
    return { total: total, units: units, invalid: invalid };
  }

  var MINUS = '<svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M5 12h14"/></svg>';
  var PLUS = '<svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M5 12h14M12 5v14"/></svg>';
  var TRASH = '<svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>';
  var FIELD = 'w-full rounded-lg border bg-navy-950 px-3 py-2 text-right font-semibold text-white focus:border-brand-400 focus:outline-none';

  function lineInfo(l) {
    var p = l.id ? catalog.byId[l.id] : null;
    var c = lineCalc(l);
    var bits = [];
    if (p) bits.push('Stock ' + p.stock + ' → <b class="text-white">' + (p.stock + l.qty) + '</b>');
    else bits.push('<b class="text-brand-300">Nouveau produit</b>');
    if (c.costOk && c.priceOk) {
      var margin = c.price - c.cost;
      bits.push('marge <b class="' + (margin > 0 ? 'text-emerald-300' : 'text-rose-400') + '">' + fmt(margin) + '</b>/u');
    }
    if (p && p.promo && c.price !== null && !isNaN(c.price) && c.price <= p.promo) bits.push('<span class="text-rose-400">≤ prix promo</span>');
    return bits.join(' · ');
  }

  function renderLines() {
    var focused = document.activeElement && el.lines.contains(document.activeElement);
    if (focused) { updateFigures(); return; }   // ne pas réécrire un champ en cours de saisie
    el.lines.innerHTML = draft.lines.map(function (l) {
      if (l.id && !catalog.byId[l.id]) return '';   // catalogue pas encore chargé
      var c = lineCalc(l);
      var code = l.id ? l.barcode : l.newp.barcode;
      return '<li data-uid="' + l.uid + '" class="rounded-xl bg-navy-800 p-3 transition">' +
        '<div class="flex items-start gap-2"><div class="min-w-0 flex-1">' +
        '<p class="truncate font-semibold text-white">' + esc(lineTitle(l)) + '</p>' +
        '<p class="text-xs text-slate-400" data-info>' + lineInfo(l) + '</p>' +
        (code ? '<p class="text-xs text-slate-500">Code-barres : ' + esc(code) + (l.id ? ' (sera associé)' : '') + '</p>' : '') +
        '</div><button type="button" data-del class="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-slate-400 hover:bg-rose-600 hover:text-white" aria-label="Retirer">' + TRASH + '</button></div>' +
        '<div class="mt-2 flex items-center gap-2"><span class="w-20 text-xs text-slate-400">Qté reçue</span>' +
        '<button type="button" class="step" data-dec aria-label="Moins">' + MINUS + '</button>' +
        '<input data-f="qty" value="' + l.qty + '" inputmode="numeric" aria-label="Quantité reçue" class="h-10 w-20 rounded-lg border border-navy-600 bg-navy-950 text-center text-lg font-bold text-white focus:border-brand-400 focus:outline-none">' +
        '<button type="button" class="step" data-inc aria-label="Plus">' + PLUS + '</button></div>' +
        '<div class="mt-2 grid grid-cols-2 gap-2">' +
        '<label class="text-xs text-slate-400">Prix d\'achat<input data-f="cost" value="' + esc(l.cost) + '" inputmode="decimal" placeholder="0" class="mt-1 ' + FIELD + (c.costOk ? ' border-navy-600' : ' border-rose-500') + '"></label>' +
        '<label class="text-xs text-slate-400">Prix de vente<input data-f="price" value="' + esc(l.price) + '" inputmode="decimal" class="mt-1 ' + FIELD + (c.priceOk ? ' border-navy-600' : ' border-rose-500') + '"></label>' +
        '</div><p class="mt-2 text-right text-sm text-slate-400">Coût : <b class="text-lg tabular-nums text-white" data-total>' + fmt(c.total) + '</b></p></li>';
    }).join('');
  }

  // Mise à jour légère pendant la saisie (sans réécrire les champs).
  function updateFigures() {
    Array.prototype.forEach.call(el.lines.querySelectorAll('[data-uid]'), function (node) {
      var l = lineByUid(node.dataset.uid);
      if (!l) return;
      var c = lineCalc(l);
      node.querySelector('[data-total]').textContent = fmt(c.total);
      node.querySelector('[data-info]').innerHTML = lineInfo(l);
      node.querySelector('[data-f="cost"]').classList.toggle('border-rose-500', !c.costOk);
      node.querySelector('[data-f="price"]').classList.toggle('border-rose-500', !c.priceOk);
    });
    renderFooter();
  }

  function renderFooter() {
    var t = totals();
    el.total.textContent = fmt(t.total);
    el.count.textContent = draft.lines.length ? '(' + draft.lines.length + ' produit' + (draft.lines.length > 1 ? 's' : '') + ', ' + t.units + ' unités)' : '';
    el.clear.classList.toggle('hidden', !draft.lines.length);
    el.empty.style.display = draft.lines.length ? 'none' : '';
    el.lines.hidden = !draft.lines.length;
    el.validate.disabled = busy || !draft.lines.length;
    el.validate.textContent = busy ? 'Enregistrement…' : 'VALIDER LA RÉCEPTION';
  }

  function render() {
    renderLines();
    renderFooter();
  }

  function lineByUid(uid) {
    for (var i = 0; i < draft.lines.length; i++) if (draft.lines[i].uid === uid) return draft.lines[i];
    return null;
  }
  function flash(uid) {
    var node = el.lines.querySelector('[data-uid="' + uid + '"]');
    if (!node) return;
    node.classList.add('ring-2', 'ring-brand-400');
    node.scrollIntoView({ block: 'nearest' });
    setTimeout(function () { node.classList.remove('ring-2', 'ring-brand-400'); }, 500);
  }

  // ---------------------------------------------------------- validation
  function submit() {
    if (busy || !draft.lines.length) return;
    if (!catalog.products.length && draft.lines.some(function (l) { return l.id; })) { toast('Catalogue non chargé : vérifiez la connexion.'); return; }
    for (var i = 0; i < draft.lines.length; i++) {
      var l = draft.lines[i], c = lineCalc(l);
      if (!c.costOk) { toast('Prix d\'achat manquant ou invalide pour « ' + lineTitle(l) + ' ».'); return; }
      if (!c.priceOk) { toast('Prix de vente invalide pour « ' + lineTitle(l) + ' ».'); return; }
    }
    if (!draft.key) { draft.key = K.uuid(); persist(); }

    var payload = draft.lines.map(function (l) {
      var c = lineCalc(l);
      if (l.id) {
        var p = catalog.byId[l.id];
        return { product_id: l.id, qty: l.qty, unit_cost: toDecimal(c.cost),
                 price: c.price !== p.price ? toDecimal(c.price) : null, barcode: l.barcode || null };
      }
      return { new: { title: l.newp.title, barcode: l.newp.barcode || null, category_id: l.newp.category_id || null,
                      price: toDecimal(c.price) },
               qty: l.qty, unit_cost: toDecimal(c.cost) };
    });

    busy = true;
    renderFooter();
    request(root.dataset.receiveUrl, {
      timeout: 45000,
      body: { lines: payload, fournisseur: draft.fournisseur, reference: draft.reference, key: draft.key }
    }).then(function (r) {
      return r.json().then(function (data) { return { status: r.status, data: data }; });
    }).then(function (res) {
      busy = false;
      var data = res.data;
      if (!data.ok) {
        K.beep(false);
        toast(data.error || 'Réception refusée.');
        loadCatalog(true);
        renderFooter();
        return;
      }
      var t = totals();
      $('done-summary').textContent = data.replayed
        ? 'Cette réception avait déjà été enregistrée.'
        : data.lines + ' produit' + (data.lines > 1 ? 's' : '') + ', ' + data.units + ' unités' +
          (data.created ? ' (' + data.created + ' nouveau' + (data.created > 1 ? 'x' : '') + ')' : '');
      $('done-total').textContent = fmt(data.replayed ? t.total : data.total);
      draft = { lines: [], fournisseur: '', reference: '', key: null };
      persist();
      el.fournisseur.value = '';
      el.reference.value = '';
      render();
      loadCatalog(true);
      el.done.hidden = false;
      $('done-new').focus();
    }).catch(function (err) {
      busy = false;
      renderFooter();
      if (err && err.handled) return;
      K.beep(false);
      toast("Connexion lente ou coupée : la réception n'est pas confirmée. Appuyez à nouveau sur Valider — elle ne sera jamais comptée deux fois.");
    });
  }

  // ------------------------------------------------------- nouveau produit
  function openNew(text) {
    var form = el.form;
    form.reset();
    el.error.textContent = '';
    el.margin.textContent = '';
    pendingBarcode = looksLikeBarcode(text) ? text : '';
    form.title.value = pendingBarcode ? '' : text;
    form.barcode.value = pendingBarcode;
    form.qty.value = String(parseQuery(el.search.value).qty || 1);
    el.hint.hidden = !pendingBarcode;
    el.hint.textContent = pendingBarcode ? 'Code-barres ' + pendingBarcode + ' inconnu : créez le produit.' : '';
    el.linkBox.hidden = !pendingBarcode;
    el.linkQ.value = '';
    el.linkResults.innerHTML = '';
    el.modal.hidden = false;
    (pendingBarcode ? form.title : (text ? form.cost : form.title)).focus();
  }
  function closeNew() { el.modal.hidden = true; }

  function newMargin() {
    var cost = parseMoney(el.form.cost.value), price = parseMoney(el.form.price.value);
    el.margin.textContent = (cost !== null && price !== null && !isNaN(cost) && !isNaN(price))
      ? 'Marge : ' + fmt(price - cost) + ' / unité' : '';
    el.margin.className = 'pb-2 text-sm font-semibold ' + (price > cost ? 'text-emerald-600' : 'text-rose-600');
  }

  function submitNew(e) {
    e.preventDefault();
    var f = el.form;
    var title = f.title.value.replace(/\s+/g, ' ').trim();
    var barcode = f.barcode.value.trim();
    var cost = parseMoney(f.cost.value), price = parseMoney(f.price.value);
    var qty = parseInt(f.qty.value.replace(/\D/g, ''), 10);
    var error = '';
    if (title.length < 2) error = 'Donnez un nom au produit.';
    else if (exactTitle(title)) error = '« ' + title + ' » existe déjà : recherchez-le plutôt.';
    else if (draft.lines.some(function (l) { return l.newp && norm(l.newp.title) === norm(title); })) error = 'Ce produit est déjà dans la réception.';
    else if (barcode && catalog.byBarcode[barcode]) error = 'Ce code-barres appartient déjà à « ' + catalog.byBarcode[barcode].title + ' ».';
    else if (barcode && draft.lines.some(function (l) { return (l.newp ? l.newp.barcode : l.barcode) === barcode; })) error = 'Ce code-barres est déjà utilisé dans la réception.';
    else if (cost === null || isNaN(cost)) error = 'Prix d\'achat obligatoire (0 si offert).';
    else if (price === null || isNaN(price) || price <= 0) error = 'Prix de vente obligatoire.';
    else if (!(qty >= 1)) error = 'Quantité reçue : au moins 1.';
    if (error) { el.error.textContent = error; return; }

    var l = { uid: K.uuid(), id: null, qty: qty, cost: toInput(cost), price: toInput(price), barcode: '',
              newp: { title: title, barcode: barcode, category_id: f.category.value ? parseInt(f.category.value, 10) : null } };
    draft.lines.unshift(l);
    closeNew();
    K.beep(true);
    changed();
    flash(l.uid);
    resetSearch();
  }

  function renderLinkResults() {
    var q = el.linkQ.value.trim();
    if (q.length < 2) { el.linkResults.innerHTML = ''; return; }
    el.linkResults.innerHTML = findProducts(q, 8).map(function (p) {
      return '<button type="button" data-link="' + p.id + '" class="flex w-full items-center gap-3 py-2.5 text-left hover:bg-slate-50">' +
        '<span class="min-w-0 flex-1 truncate font-medium">' + esc(p.title) + '</span>' +
        '<span class="text-xs text-slate-500">' + (p.barcode ? 'code ' + esc(p.barcode) : 'sans code') + '</span></button>';
    }).join('') || '<p class="py-2 text-sm text-slate-500">Aucun produit.</p>';
  }

  // ------------------------------------------------------------ événements
  el.search.addEventListener('input', function () { setSearching(); renderResults(); });
  el.search.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { resetSearch(); return; }
    if (e.key !== 'Enter') return;
    e.preventDefault();
    var q = parseQuery(el.search.value);
    if (!q.text) return;
    var p = catalog.byBarcode[q.text] || exactTitle(q.text);
    if (!p) {
      var list = findProducts(q.text);
      if (list.length === 1 && !looksLikeBarcode(q.text)) p = list[0];
    }
    if (p) { addExisting(p, q.qty); resetSearch(); return; }
    if (looksLikeBarcode(q.text) || !findProducts(q.text).length) { K.beep(false); openNew(q.text); }
  });

  el.results.addEventListener('click', function (e) {
    var add = e.target.closest('[data-add]');
    if (add) {
      addExisting(catalog.byId[add.dataset.add], parseQuery(el.search.value).qty);
      resetSearch();
      return;
    }
    if (e.target.closest('[data-create]')) openNew(parseQuery(el.search.value).text);
  });

  el.lines.addEventListener('click', function (e) {
    var item = e.target.closest('[data-uid]');
    var b = e.target.closest('button');
    if (!item || !b) return;
    var l = lineByUid(item.dataset.uid);
    if (b.hasAttribute('data-inc')) { l.qty += 1; changed(); }
    else if (b.hasAttribute('data-dec')) { if (l.qty > 1) { l.qty -= 1; changed(); } }
    else if (b.hasAttribute('data-del')) {
      draft.lines = draft.lines.filter(function (x) { return x !== l; });
      changed();
    }
  });
  el.lines.addEventListener('input', function (e) {
    var f = e.target.dataset.f;
    if (!f) return;
    var l = lineByUid(e.target.closest('[data-uid]').dataset.uid);
    if (f === 'qty') {
      var qty = parseInt(e.target.value.replace(/\D/g, ''), 10);
      if (qty >= 1) l.qty = Math.min(qty, 1000000);
    } else {
      l[f] = e.target.value;
    }
    draft.key = null;
    persist();
    updateFigures();
  });
  el.lines.addEventListener('focusin', function (e) { if (e.target.dataset.f) e.target.select(); });
  el.lines.addEventListener('keydown', function (e) { if (e.target.dataset.f && e.key === 'Enter') e.target.blur(); });
  el.lines.addEventListener('focusout', function () { setTimeout(render, 0); });

  el.clear.addEventListener('click', function () {
    if (!window.confirm('Vider la réception ?')) return;
    draft.lines = [];
    changed();
  });
  el.fournisseur.addEventListener('input', function () { draft.fournisseur = el.fournisseur.value; draft.key = null; persist(); });
  el.reference.addEventListener('input', function () { draft.reference = el.reference.value; draft.key = null; persist(); });
  el.validate.addEventListener('click', submit);

  el.form.addEventListener('submit', submitNew);
  el.form.addEventListener('input', function (e) { if (e.target.name === 'cost' || e.target.name === 'price') newMargin(); });
  el.modal.addEventListener('click', function (e) {
    if (e.target === el.modal || e.target.closest('[data-close]')) return closeNew();
    var link = e.target.closest('[data-link]');
    if (!link) return;
    var p = catalog.byId[link.dataset.link];
    if (p.barcode && p.barcode !== pendingBarcode &&
        !window.confirm('« ' + p.title + ' » a déjà le code ' + p.barcode + '. Le remplacer par ' + pendingBarcode + ' ?')) return;
    closeNew();
    addExisting(p, parseInt(el.form.qty.value, 10) || 1, pendingBarcode);
    resetSearch();
  });
  el.linkQ.addEventListener('input', renderLinkResults);

  $('done-new').addEventListener('click', function () { el.done.hidden = true; resetSearch(); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'F2') { e.preventDefault(); el.search.focus(); }
    if (e.key === 'F9' || (e.ctrlKey && e.key === 'Enter')) { e.preventDefault(); submit(); }
    if (e.key === 'Escape' && !el.modal.hidden) closeNew();
  });
  window.addEventListener('online', function () { setOnline(true); loadCatalog(); });
  window.addEventListener('offline', function () { setOnline(false); });

  // ------------------------------------------------------------- démarrage
  el.fournisseur.value = draft.fournisseur;
  el.reference.value = draft.reference;
  loadCatalog();
  render();
  if (K.finePointer) el.search.focus();
})();
