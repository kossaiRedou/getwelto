/* WELTO — utilitaires communs (≈1 Ko). Aucune dépendance. */
(function () {
  'use strict';
  var doc = document;

  // Menu latéral sur mobile/tablette
  doc.addEventListener('click', function (e) {
    var t = e.target.closest('[data-toggle-nav]');
    if (t) {
      doc.body.classList.toggle('nav-open');
      return;
    }
    if (doc.body.classList.contains('nav-open') && e.target.closest('[data-nav-backdrop]')) {
      doc.body.classList.remove('nav-open');
    }
  });

  // Confirmation avant une action sensible : <form data-confirm="…">
  doc.addEventListener('submit', function (e) {
    var form = e.target;
    var msg = form.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) {
      e.preventDefault();
      return;
    }
    // Évite le double envoi d'un formulaire (réseau lent)
    if (form.dataset.sent) {
      e.preventDefault();
      return;
    }
    form.dataset.sent = '1';
    setTimeout(function () { delete form.dataset.sent; }, 8000);
  });

  // Les messages de succès disparaissent seuls
  setTimeout(function () {
    doc.querySelectorAll('[data-autohide]').forEach(function (el) { el.remove(); });
  }, 5000);
})();
