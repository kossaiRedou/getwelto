/*
 * WELTO — scan de codes-barres avec l'appareil photo (dépannage quand il n'y a
 * pas de douchette). Sans dépendance au chargement de la page :
 * - Chrome/Android : lecteur intégré au navigateur (BarcodeDetector).
 * - Safari/iPad et autres : bibliothèque ZXing (≈100 Ko), téléchargée
 *   seulement au premier usage puis gardée en cache.
 * Nécessite HTTPS (ou localhost) : sinon le navigateur refuse la caméra.
 *
 * Usage : WeltoScanner.open({ zxingUrl, onCode: function (code) { … } })
 *   onCode renvoie false pour fermer la caméra (ex. ouvrir un formulaire),
 *   sinon le scan continue (plusieurs produits à la suite).
 */
(function () {
  'use strict';

  var FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'itf', 'qr_code'];
  var SCAN_EVERY_MS = 120;
  // Un même code n'est recompté qu'après être sorti du cadre (quelques images sans code) :
  // un produit laissé devant la caméra n'est jamais ajouté en rafale.
  var CLEAR_AFTER_EMPTY_FRAMES = 4;

  var state = null;
  var zxingPromise = null;

  function supported() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }

  function loadZXing(url) {
    if (window.ZXing) return Promise.resolve(window.ZXing);
    if (!zxingPromise) {
      zxingPromise = new Promise(function (resolve, reject) {
        var s = document.createElement('script');
        s.src = url;
        s.async = true;
        s.onload = function () { window.ZXing ? resolve(window.ZXing) : reject(new Error('zxing')); };
        s.onerror = function () { zxingPromise = null; reject(new Error('zxing')); };
        document.head.appendChild(s);
      });
    }
    return zxingPromise;
  }

  // Renvoie une fonction detect(video, canvas) → Promise<texte|null>.
  function makeDetector(zxingUrl) {
    if ('BarcodeDetector' in window) {
      return window.BarcodeDetector.getSupportedFormats().then(function (formats) {
        var wanted = FORMATS.filter(function (f) { return formats.indexOf(f) !== -1; });
        if (wanted.indexOf('ean_13') === -1) throw new Error('formats');
        var detector = new window.BarcodeDetector({ formats: wanted });
        return function (video) {
          return detector.detect(video).then(function (codes) { return codes.length ? codes[0].rawValue : null; });
        };
      }).catch(function () { return zxingDetector(zxingUrl); });
    }
    return zxingDetector(zxingUrl);
  }

  function zxingDetector(url) {
    return loadZXing(url).then(function (Z) {
      var hints = new Map();
      hints.set(Z.DecodeHintType.POSSIBLE_FORMATS, [
        Z.BarcodeFormat.EAN_13, Z.BarcodeFormat.EAN_8, Z.BarcodeFormat.UPC_A, Z.BarcodeFormat.UPC_E,
        Z.BarcodeFormat.CODE_128, Z.BarcodeFormat.CODE_39, Z.BarcodeFormat.ITF, Z.BarcodeFormat.QR_CODE
      ]);
      hints.set(Z.DecodeHintType.TRY_HARDER, true);
      var reader = new Z.MultiFormatReader();
      reader.setHints(hints);
      return function (video, canvas) {
        // Zone centrale de l'image, réduite : plus rapide sur les tablettes modestes.
        var vw = video.videoWidth, vh = video.videoHeight;
        if (!vw || !vh) return Promise.resolve(null);
        var cw = Math.min(vw, Math.round(vh * 1.4)), ch = Math.round(cw / 1.4);
        var sx = (vw - cw) / 2, sy = (vh - ch) / 2;
        var scale = Math.min(1, 800 / cw);
        canvas.width = Math.round(cw * scale);
        canvas.height = Math.round(ch * scale);
        canvas.getContext('2d', { willReadFrequently: true }).drawImage(video, sx, sy, cw, ch, 0, 0, canvas.width, canvas.height);
        try {
          var bitmap = new Z.BinaryBitmap(new Z.HybridBinarizer(new Z.HTMLCanvasElementLuminanceSource(canvas)));
          return Promise.resolve(reader.decode(bitmap).getText());
        } catch (e) {
          return Promise.resolve(null);   // aucun code dans cette image
        } finally {
          reader.reset();
        }
      };
    });
  }

  function overlay() {
    var root = document.createElement('div');
    root.className = 'fixed inset-0 z-[70] flex flex-col bg-black text-white';
    root.innerHTML =
      '<div class="flex items-center gap-3 p-3 pt-[max(.75rem,env(safe-area-inset-top))]">' +
        '<p class="flex-1 text-sm font-semibold" data-scan-title>Scanner un code-barres</p>' +
        '<button type="button" data-scan-torch hidden class="rounded-xl bg-white/10 px-3 py-2 text-sm font-semibold">Lampe</button>' +
        '<button type="button" data-scan-close class="rounded-xl bg-white/10 px-4 py-2 text-sm font-semibold">Fermer</button>' +
      '</div>' +
      '<div class="relative min-h-0 flex-1 overflow-hidden">' +
        '<video data-scan-video class="absolute inset-0 h-full w-full object-cover" playsinline muted autoplay></video>' +
        '<div class="pointer-events-none absolute inset-0 flex items-center justify-center p-8">' +
          '<div data-scan-frame class="aspect-[1.6] w-full max-w-md rounded-2xl border-4 border-white/80 shadow-[0_0_0_9999px_rgba(0,0,0,.45)] transition-colors"></div>' +
        '</div>' +
      '</div>' +
      '<p data-scan-status class="min-h-14 p-4 pb-[max(1rem,env(safe-area-inset-bottom))] text-center text-sm font-semibold">Démarrage de la caméra…</p>';
    document.body.appendChild(root);
    return root;
  }

  function open(options) {
    if (state) return;
    if (!supported()) {
      alert("Cet appareil ou ce navigateur ne permet pas d'utiliser la caméra.");
      return;
    }
    if (!window.isSecureContext) {
      alert("La caméra n'est disponible que sur une adresse sécurisée (https).");
      return;
    }
    var root = overlay();
    var q = function (sel) { return root.querySelector(sel); };
    state = {
      root: root, video: q('[data-scan-video]'), status: q('[data-scan-status]'), frame: q('[data-scan-frame]'),
      canvas: document.createElement('canvas'), stream: null, timer: null, closed: false,
      last: '', empty: 0, candidate: '', options: options
    };
    if (options.title) q('[data-scan-title]').textContent = options.title;
    q('[data-scan-close]').addEventListener('click', close);
    document.addEventListener('keydown', onKey);
    document.addEventListener('visibilitychange', onHidden);

    navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }
    }).then(function (stream) {
      if (!state || state.closed) { stream.getTracks().forEach(function (t) { t.stop(); }); return; }
      state.stream = stream;
      state.video.srcObject = stream;
      setupTorch(stream, q('[data-scan-torch]'));
      setStatus('Chargement du lecteur…');
      return makeDetector(options.zxingUrl).then(function (detect) {
        if (!state || state.closed) return;
        state.detect = detect;
        setStatus('Placez le code-barres dans le cadre');
        loop();
      });
    }).catch(function (err) {
      var name = err && err.name;
      setStatus(name === 'NotAllowedError' ? "Accès à la caméra refusé : autorisez-le dans les réglages du navigateur."
        : name === 'NotFoundError' ? 'Aucune caméra trouvée sur cet appareil.'
        : 'Impossible de démarrer la caméra ou le lecteur.', true);
    });
  }

  function setupTorch(stream, button) {
    var track = stream.getVideoTracks()[0];
    var caps = track && track.getCapabilities ? track.getCapabilities() : {};
    if (!caps.torch) return;
    var on = false;
    button.hidden = false;
    button.addEventListener('click', function () {
      on = !on;
      track.applyConstraints({ advanced: [{ torch: on }] }).catch(function () {});
      button.classList.toggle('bg-amber-400', on);
      button.classList.toggle('text-black', on);
    });
  }

  function setStatus(text, error) {
    if (!state) return;
    state.status.textContent = text;
    state.status.classList.toggle('text-rose-300', !!error);
  }

  function loop() {
    if (!state || state.closed) return;
    var s = state;
    var run = s.video.readyState >= 2 ? s.detect(s.video, s.canvas) : Promise.resolve(null);
    run.catch(function () { return null; }).then(function (code) {
      if (!state || state.closed) return;
      if (code) {
        s.empty = 0;
        found(String(code).trim());
      } else if (++s.empty >= CLEAR_AFTER_EMPTY_FRAMES) {
        s.last = '';
        s.candidate = '';
      }
      s.timer = setTimeout(loop, SCAN_EVERY_MS);
    });
  }

  function found(code) {
    var s = state;
    // Deux lectures identiques de suite : évite les erreurs de lecture.
    if (code !== s.candidate) { s.candidate = code; return; }
    if (code === s.last) return;
    s.last = code;
    s.candidate = '';
    s.frame.style.borderColor = '#34d399';
    setTimeout(function () { s.frame.style.borderColor = ''; }, 400);
    if (navigator.vibrate) navigator.vibrate(60);
    var result = s.options.onCode(code);
    if (result === false) { close(); return; }
    setStatus((typeof result === 'string' ? result : 'Code lu : ' + code) +
      ' · Pour le compter à nouveau, retirez-le du cadre puis représentez-le.');
  }

  function onKey(e) { if (e.key === 'Escape') close(); }
  function onHidden() { if (document.hidden) close(); }

  function close() {
    if (!state) return;
    var s = state;
    state = null;
    s.closed = true;
    clearTimeout(s.timer);
    if (s.stream) s.stream.getTracks().forEach(function (t) { t.stop(); });
    document.removeEventListener('keydown', onKey);
    document.removeEventListener('visibilitychange', onHidden);
    s.root.remove();
    if (s.options.onClose) s.options.onClose();
  }

  window.WeltoScanner = { supported: supported, open: open, close: close };
})();
