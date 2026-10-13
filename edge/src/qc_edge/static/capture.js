// PartQC capture page (SPEC-007 section 4.4). Plain JS, no framework, no external resource.
// The photo is always resized (longest side <= 1280 px) and re-encoded as JPEG q=0.9 before it is
// sent; the original file is never uploaded (section 4.7).
(function () {
  "use strict";

  var MAX_SIDE = 1280;
  var JPEG_QUALITY = 0.9;
  var LOT_KEY = "partqc.lot_id";

  var token = new URLSearchParams(window.location.search).get("t") || "";
  var lotInput = document.getElementById("lot_id");
  var modeSelect = document.getElementById("mode");
  var shoot = document.getElementById("shoot");
  var fileInput = shoot.querySelector('input[type="file"]');
  var statusLine = document.getElementById("status");
  var card = document.getElementById("result");

  var MESSAGES = {
    prepare: "Não foi possível preparar a foto. Tente de novo.",
    network: "Falha de rede: confira o Wi-Fi e tente de novo.",
    401: "Sessão inválida. Leia o QR code no console de novo.",
    413: "Foto grande demais para a borda.",
    415: "Imagem inválida ou formato não suportado.",
    422: "Dados inválidos: o lote aceita só letras, números, - e _ (até 40).",
    501: "Modo coleta ainda não disponível.",
    busy: "Borda ocupada. Tente de novo.",
    noModel: "Modelo não carregado na borda.",
    persist: "A borda não conseguiu gravar a inspeção. Tente de novo.",
    other: "Erro na borda. Tente de novo.",
  };

  // localStorage can throw (private mode, storage disabled): the lot is then just not remembered.
  function saveLot() {
    try { window.localStorage.setItem(LOT_KEY, lotInput.value.trim()); } catch (e) { /* ignore */ }
  }

  function loadLot() {
    try { return window.localStorage.getItem(LOT_KEY) || ""; } catch (e) { return ""; }
  }

  function showStatus(text, isError) {
    statusLine.textContent = text;
    statusLine.className = isError ? "status error" : "status";
  }

  function setBusy(busy) {
    fileInput.disabled = busy;
    shoot.classList.toggle("busy", busy);
  }

  function errorMessage(status, detail) {
    if (status === 503) {
      if (detail === "server busy") return MESSAGES.busy;
      if (detail === "model not loaded") return MESSAGES.noModel;
      if (detail === "failed to persist inspection") return MESSAGES.persist;
      return MESSAGES.other;
    }
    return MESSAGES[status] || MESSAGES.other;
  }

  // Decodes the file with the EXIF orientation applied. Resolves to {source, width, height, done}.
  function decode(file) {
    if (window.createImageBitmap) {
      return createImageBitmap(file, { imageOrientation: "from-image" }).then(
        function (bitmap) {
          return { source: bitmap, width: bitmap.width, height: bitmap.height,
            done: function () { bitmap.close(); } };
        },
        function () { return decodeWithImg(file); }
      );
    }
    return decodeWithImg(file);
  }

  function decodeWithImg(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        resolve({ source: img, width: img.naturalWidth, height: img.naturalHeight,
          done: function () { URL.revokeObjectURL(url); } });
      };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error("decode")); };
      img.src = url;
    });
  }

  // Resizes (never enlarges) and re-encodes as JPEG. Rejects when the canvas cannot encode.
  function prepare(file) {
    return decode(file).then(function (decoded) {
      try {
        var scale = Math.min(1, MAX_SIDE / Math.max(decoded.width, decoded.height));
        var canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(decoded.width * scale));
        canvas.height = Math.max(1, Math.round(decoded.height * scale));
        canvas.getContext("2d").drawImage(decoded.source, 0, 0, canvas.width, canvas.height);
      } finally {
        decoded.done();
      }
      return new Promise(function (resolve, reject) {
        canvas.toBlob(function (blob) {
          if (blob) resolve(blob); else reject(new Error("encode"));
        }, "image/jpeg", JPEG_QUALITY);
      });
    });
  }

  function showResult(body, totalMs) {
    var labels = body.labels_pt;
    var inspection = body.inspection;
    var kind = body.approved === true ? "approved" : body.approved === false ? "rejected" : "unknown";
    card.className = "card " + kind + (inspection.needs_review ? " needs-review" : "");
    document.getElementById("verdict").textContent = labels.verdict;
    document.getElementById("object_type").textContent = labels.object_type;
    document.getElementById("grade").textContent = labels.grade === null ? "" : labels.grade;
    document.getElementById("review").hidden = !inspection.needs_review;
    document.getElementById("latency").textContent = String(inspection.latency_ms);
    document.getElementById("total").textContent = String(Math.round(totalMs));
    card.hidden = false;
  }

  function send(blob, startedAt) {
    var form = new FormData();
    form.append("image", blob, "capture.jpg");
    form.append("lot_id", lotInput.value.trim());
    form.append("mode", modeSelect.value);
    return fetch("/api/capture", {
      method: "POST",
      headers: { "X-Session-Token": token },
      body: form,
      cache: "no-store",
    }).then(
      function (response) {
        return response.json().catch(function () { return {}; }).then(function (body) {
          if (response.ok) {
            showResult(body, performance.now() - startedAt);
            showStatus("", false);
          } else {
            showStatus(errorMessage(response.status, body.detail), true);
          }
        });
      },
      function () { showStatus(MESSAGES.network, true); }
    );
  }

  function onPhoto() {
    var file = fileInput.files && fileInput.files[0];
    if (!file) return;
    var startedAt = performance.now();
    saveLot();
    setBusy(true);
    card.hidden = true;
    showStatus("Enviando…", false);
    prepare(file)
      .then(
        function (blob) { return send(blob, startedAt); },
        function () { showStatus(MESSAGES.prepare, true); }
      )
      .catch(function () { showStatus(MESSAGES.other, true); })
      .then(function () {
        setBusy(false);
        fileInput.value = "";
      });
  }

  lotInput.value = loadLot();
  lotInput.addEventListener("change", saveLot);
  fileInput.addEventListener("change", onPhoto);
  if (!token) showStatus(MESSAGES[401], true);
})();
