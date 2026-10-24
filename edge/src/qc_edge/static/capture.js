// PartQC capture page (SPEC-007 section 4.4, SPEC-010 section 4.3). Plain JS, no framework, no
// external resource. The photo is always resized (longest side <= 1280 px) and re-encoded as JPEG
// q=0.9 before it is sent; the original file is never uploaded (SPEC-007 section 4.7).
(function () {
  "use strict";

  var MAX_SIDE = 1280, JPEG_QUALITY = 0.9;
  var STORE_PREFIX = "partqc.";
  var COLLECT = ["item_id", "object_type", "grade", "labeler", "angle", "notes"];
  var SAVED = ["lot_id", "mode"].concat(COLLECT);
  var ITEM_ID_RE = /^[SNOT]-[0-9]{3}$/;  // same rule as the server (re.fullmatch)
  var PREFIX_TYPES = { S: ["screw"], N: ["nut"], O: ["other"],  // T: hand tools (SPEC-016)
    T: ["pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver"] };

  function el(id) { return document.getElementById(id); }
  var token = new URLSearchParams(window.location.search).get("t") || "";
  var fields = {};
  SAVED.forEach(function (name) { fields[name] = el(name); });
  var shoot = el("shoot");
  var fileInput = shoot.querySelector('input[type="file"]');
  var statusLine = el("status"), card = el("result"), savedCard = el("saved");

  var MESSAGES = {
    prepare: "Não foi possível preparar a foto. Tente de novo.",
    network: "Falha de rede: confira o Wi-Fi e tente de novo.",
    401: "Sessão inválida. Leia o QR code no console de novo.",
    413: "Foto grande demais para a borda.",
    415: "Imagem inválida ou formato não suportado.",
    422: "Dados inválidos: o lote aceita só letras, números, - e _ (até 40).",
    collect422: "Dados da coleta inválidos: confira peça, tipo, grau, ângulo e observações.",
    itemId: "Peça inválida: use S-000 (parafuso), N-000 (porca), T-000 (ferramenta) ou O-000 "
      + "(outro), conforme o tipo.",
    noGrade: "Escolha o grau da peça.",
    other: "Erro na borda. Tente de novo.",
  };
  // Messages chosen by the "detail" of the response (503, 409 and 500 of both modes).
  var DETAILS = {
    "server busy": "Borda ocupada. Tente de novo.",
    "model not loaded": "Modelo não carregado na borda.",
    "failed to persist inspection": "A borda não conseguiu gravar a inspeção. Tente de novo.",
    "item_id already registered with another object_type": "Peça já registrada com outro tipo.",
    "capture already exists, try again": "Foto repetida no mesmo segundo. Tente de novo.",
    "manifest header mismatch": "O manifest.csv do notebook tem um cabeçalho inesperado.",
    "failed to write dataset": "A borda não conseguiu gravar a foto do dataset. Tente de novo.",
  };

  // localStorage can throw (private mode, storage disabled): the fields are then not remembered.
  function save() {
    try {
      SAVED.forEach(function (n) { window.localStorage.setItem(STORE_PREFIX + n, value(n)); });
    } catch (e) { /* ignore */ }
  }
  function load() {
    try {
      SAVED.forEach(function (name) {
        var stored = window.localStorage.getItem(STORE_PREFIX + name);
        if (stored !== null) fields[name].value = stored;
      });
    } catch (e) { /* ignore */ }
  }

  function value(name) {
    var raw = fields[name].value;
    return name === "lot_id" || name === "item_id" ? raw.trim() : raw;
  }
  function collecting() { return fields.mode.value === "collect"; }

  // Shows the collect fields; the grade is disabled and empty for "other".
  function syncForm() {
    el("collect-fields").hidden = !collecting();
    var isOther = fields.object_type.value === "other";
    if (isOther) fields.grade.value = "";
    fields.grade.disabled = isOther;
  }

  function collectProblem() {
    var itemId = value("item_id"), type = value("object_type");
    var types = ITEM_ID_RE.test(itemId) ? PREFIX_TYPES[itemId[0]] : [];
    if (types.indexOf(type) < 0) return MESSAGES.itemId;
    if (type !== "other" && !value("grade")) return MESSAGES.noGrade;
    return "";
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
    if (Object.prototype.hasOwnProperty.call(DETAILS, detail)) return DETAILS[detail];
    if (status === 422 && collecting()) return MESSAGES.collect422;
    return MESSAGES[status] || MESSAGES.other;
  }

  // Decodes the file with the EXIF orientation applied. Resolves to {source, width, height, done}.
  function decode(file) {
    if (!window.createImageBitmap) return decodeWithImg(file);
    return createImageBitmap(file, { imageOrientation: "from-image" }).then(function (bitmap) {
      return { source: bitmap, width: bitmap.width, height: bitmap.height,
        done: function () { bitmap.close(); } };
    }, function () { return decodeWithImg(file); });
  }
  function decodeWithImg(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file), img = new Image();
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
      var canvas = document.createElement("canvas");
      try {
        var scale = Math.min(1, MAX_SIDE / Math.max(decoded.width, decoded.height));
        canvas.width = Math.max(1, Math.round(decoded.width * scale));
        canvas.height = Math.max(1, Math.round(decoded.height * scale));
        canvas.getContext("2d").drawImage(decoded.source, 0, 0, canvas.width, canvas.height);
      } finally { decoded.done(); }
      return new Promise(function (resolve, reject) {
        canvas.toBlob(function (blob) {
          if (blob) resolve(blob); else reject(new Error("encode"));
        }, "image/jpeg", JPEG_QUALITY);
      });
    });
  }

  function showResult(body, totalMs) {
    var labels = body.labels_pt, inspection = body.inspection;
    var kind = body.approved === true ? "approved" : body.approved === false ? "rejected" : "unknown";
    card.className = "card " + kind + (inspection.needs_review ? " needs-review" : "");
    el("verdict").textContent = labels.verdict;
    el("object_type_label").textContent = labels.object_type;
    el("grade_label").textContent = labels.grade === null ? "" : labels.grade;
    el("review").hidden = !inspection.needs_review;
    el("latency").textContent = String(inspection.latency_ms);
    el("total").textContent = String(Math.round(totalMs));
    card.hidden = false;
  }

  // Collect mode: the angle moves on after each saved photo; after 4 it goes back to 0.
  function showSaved(body) {
    el("saved-text").textContent = "Salvo: " + body.item_id + ", ângulo " + body.angle
      + " (fotos desta peça: " + body.item_images + ")";
    var complete = body.angle >= 4;
    fields.angle.value = String(complete ? 0 : body.angle + 1);
    el("complete").hidden = !complete;
    save(); savedCard.hidden = false;
  }

  function send(blob, startedAt) {
    var form = new FormData();
    form.append("image", blob, "capture.jpg");
    form.append("lot_id", value("lot_id"));
    form.append("mode", value("mode"));
    if (collecting()) COLLECT.forEach(function (name) { form.append(name, value(name)); });
    return fetch("/api/capture", {
      method: "POST", headers: { "X-Session-Token": token }, body: form, cache: "no-store",
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok) return showStatus(errorMessage(response.status, body.detail), true);
        showStatus("", false);
        if (body.mode === "collect") return showSaved(body);
        showResult(body, performance.now() - startedAt);
      });
    }, function () { showStatus(MESSAGES.network, true); });
  }

  function onPhoto() {
    var file = fileInput.files && fileInput.files[0];
    if (!file) return;
    var startedAt = performance.now();
    save();
    card.hidden = savedCard.hidden = true;
    var problem = collecting() ? collectProblem() : "";
    if (problem) { showStatus(problem, true); fileInput.value = ""; return; }
    setBusy(true); showStatus("Enviando…", false);
    prepare(file)
      .then(function (blob) { return send(blob, startedAt); },
        function () { showStatus(MESSAGES.prepare, true); })
      .catch(function () { showStatus(MESSAGES.other, true); })
      .then(function () { setBusy(false); fileInput.value = ""; });
  }

  function onFieldChange() { syncForm(); save(); }
  load(); syncForm();
  SAVED.forEach(function (name) { fields[name].addEventListener("change", onFieldChange); });
  fileInput.addEventListener("change", onPhoto);
  if (!token) showStatus(MESSAGES[401], true);
})();
