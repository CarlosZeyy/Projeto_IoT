// PartQC live page (SPEC-019 section 4.5). Plain JS, no framework, no external resource, no secret:
// the token comes from the URL. Frames are sent only to this notebook (R-02), and at most one
// request is in flight: a frame that comes up in the meantime is dropped, never queued.
(function () {
  "use strict";

  var MAX_SIDE = 640, JPEG_QUALITY = 0.8, EMIT_SHOW_MS = 2000, FRAME_TIMEOUT_MS = 15000;
  var BAND_MIN_PX = 56, BAND_LINE_PX = 22, BAND_MARGIN = 10, BAND_FONT = "system-ui, sans-serif";
  var LOT_STORE_KEY = "partqc.lot_id";  // the same key of the capture page
  var LOT_RE = /^[A-Za-z0-9_-]{1,40}$/;  // same rule as the server (re.fullmatch)
  var STATE_LABELS = { IDLE: "aguardando peça", DETECTING: "analisando", EMIT: "peça registrada",
    WAIT_REMOVAL: "retire a peça" };
  var MESSAGES = {
    secure: "O vídeo ao vivo exige HTTPS (configure EDGE_TLS_CERT e EDGE_TLS_KEY).",
    camera: "Não foi possível abrir a câmera: confira a permissão do navegador.",
    lot: "Informe o lote: só letras, números, - e _ (até 40).",
    network: "Falha de rede: confira o Wi-Fi.",
    401: "Sessão inválida. Leia o QR code no console de novo.",
    413: "Quadro grande demais para a borda.",
    415: "Quadro inválido.",
    422: "Dados inválidos: confira o lote.",
    429: "Muitas sessões de vídeo abertas na borda. Feche outra página.",
    other: "Erro na borda. Tentando de novo.",
  };
  // Messages chosen by the "detail" of the response (503 and 500).
  var DETAILS = {
    "server busy": "Borda ocupada. Quadro descartado.",
    "model not loaded": "Modelo não carregado na borda.",
    "failed to persist inspection": "A borda não conseguiu gravar a inspeção. Tentando de novo.",
    "inference failed": "A borda não conseguiu analisar o quadro. Tentando de novo.",
  };

  function el(id) { return document.getElementById(id); }
  var main = el("live"), video = el("video"), overlay = el("overlay"), lotField = el("lot_id");
  var statusLine = el("status");
  var FPS = Number(main.dataset.fps) || 2, LABELS = JSON.parse(main.dataset.labels);
  var token = new URLSearchParams(window.location.search).get("t") || "";
  var frameCanvas = document.createElement("canvas");
  var inFlight = false, stopped = false, timer = null, stream = null;
  var last = null, emitted = null, emittedTimer = null;

  function showStatus(text, isError) {
    statusLine.textContent = text;
    statusLine.className = isError ? "status error" : "status";
  }

  if (!window.isSecureContext) { showStatus(MESSAGES.secure, true); return; }

  // 16 random bytes in hexadecimal: 32 characters of the alphabet the server accepts.
  function newSession() {
    var bytes = window.crypto.getRandomValues(new Uint8Array(16));
    return Array.prototype.map.call(bytes, function (byte) {
      return ("0" + byte.toString(16)).slice(-2);
    }).join("");
  }
  var session = newSession();

  // The lot of the frames is the confirmed one, and never the field in the middle of the typing: a
  // pause with the part on the table would record the inspection in an incomplete lot, and the lot
  // is the subgroup of the p chart (ADR-013).
  var lot = "";
  function confirmLot() {
    lot = lotField.value.trim();
    try { window.localStorage.setItem(LOT_STORE_KEY, lot); } catch (e) { /* ignore */ }
  }
  function loadLot() {
    try {
      var stored = window.localStorage.getItem(LOT_STORE_KEY);
      if (stored !== null) lotField.value = stored;
    } catch (e) { /* ignore */ }
    lot = lotField.value.trim();
  }

  // Largest font, up to `size`, that keeps the whole line within `maxWidth`.
  function fitFont(ctx, line, weight, size, maxWidth) {
    ctx.font = weight + size + "px " + BAND_FONT;
    while (size > 1 && ctx.measureText(line).width > maxWidth) {
      size -= 1;
      ctx.font = weight + size + "px " + BAND_FONT;
    }
  }

  // No line may be cut, at any width or video proportion: the verdict and the warning of a
  // provisional model are here (section 4.4, R-06).
  function drawBand(ctx, width, height, color, lines) {
    var band = Math.max(BAND_MIN_PX, BAND_LINE_PX * lines.length, Math.round(height / 6));
    var row = band / lines.length;
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, width, band);
    ctx.fillStyle = "#fff";
    ctx.textBaseline = "middle";
    lines.forEach(function (line, index) {
      fitFont(ctx, line, index === 0 ? "bold " : "", Math.round(band / (lines.length + 0.6)), width - 2 * BAND_MARGIN);
      ctx.fillText(line, BAND_MARGIN, (index + 0.5) * row);
    });
  }

  function emittedLines(inspection) {
    var grade = inspection.grade === null ? "" : LABELS.grades[inspection.grade];
    return ["Registrada: " + LABELS.object_types[inspection.object_type] + " " + grade,
      LABELS.verdicts[inspection.grade === null ? "" : inspection.grade]];
  }

  function resultLines(step) {
    var labels = step.result.labels_pt;
    return [labels.object_type + (labels.grade === null ? "" : " " + labels.grade),
      labels.verdict,
      Math.round(step.result.type_confidence * 100) + "% · " + (STATE_LABELS[step.state] || step.state)];
  }

  // Result, confidence, state and stability bar, over the video.
  function draw() {
    var width = overlay.clientWidth, height = overlay.clientHeight;
    if (!width || !height) return;
    overlay.width = width;
    overlay.height = height;
    var ctx = overlay.getContext("2d");
    ctx.clearRect(0, 0, width, height);
    if (emitted) {
      drawBand(ctx, width, height, "rgba(30, 142, 62, 0.9)", emittedLines(emitted));
    } else if (last) {
      drawBand(ctx, width, height, "rgba(0, 0, 0, 0.6)", resultLines(last));
    }
    if (last) {
      ctx.fillStyle = "rgba(255, 255, 255, 0.35)";
      ctx.fillRect(0, height - 12, width, 12);
      ctx.fillStyle = "#f4c20d";
      ctx.fillRect(0, height - 12, width * last.stability, 12);
    }
  }

  function showEmitted(inspection) {
    emitted = inspection;
    window.clearTimeout(emittedTimer);
    emittedTimer = window.setTimeout(function () { emitted = null; draw(); }, EMIT_SHOW_MS);
  }

  function stop() {
    stopped = true;
    window.clearInterval(timer);
    if (stream) stream.getTracks().forEach(function (track) { track.stop(); });
  }

  function encodeFrame() {
    var width = video.videoWidth, height = video.videoHeight;
    var scale = Math.min(1, MAX_SIDE / Math.max(width, height));
    frameCanvas.width = Math.max(1, Math.round(width * scale));
    frameCanvas.height = Math.max(1, Math.round(height * scale));
    frameCanvas.getContext("2d").drawImage(video, 0, 0, frameCanvas.width, frameCanvas.height);
    return new Promise(function (resolve, reject) {
      frameCanvas.toBlob(function (blob) {
        if (blob) resolve(blob); else reject(new Error("encode"));
      }, "image/jpeg", JPEG_QUALITY);
    });
  }

  function handleResponse(response) {
    return response.json().catch(function () { return {}; }).then(function (body) {
      if (!response.ok) {
        var known = Object.prototype.hasOwnProperty.call(DETAILS, body.detail);
        showStatus(known ? DETAILS[body.detail] : MESSAGES[response.status] || MESSAGES.other, true);
        if (response.status === 401) stop();
        return;
      }
      showStatus("", false);
      last = body;
      if (body.inspection) showEmitted(body.inspection);
      draw();
    });
  }

  function send(blob) {
    var form = new FormData();
    form.append("image", blob, "frame.jpg");
    form.append("lot_id", lot);
    form.append("session", session);
    var abort = new AbortController();
    var timeout = window.setTimeout(function () { abort.abort(); }, FRAME_TIMEOUT_MS);
    return fetch("/api/live/frame", {
      method: "POST", headers: { "X-Session-Token": token }, body: form, cache: "no-store",
      signal: abort.signal,
    }).then(handleResponse, function () { showStatus(MESSAGES.network, true); })
      .then(function () { window.clearTimeout(timeout); });
  }

  function tick() {
    if (inFlight || stopped || document.hidden || !video.videoWidth) return;  // frame dropped
    if (!LOT_RE.test(lot)) { showStatus(MESSAGES.lot, true); return; }
    inFlight = true;
    encodeFrame().then(send).catch(function () { showStatus(MESSAGES.other, true); })
      .then(function () { inFlight = false; });
  }

  loadLot();
  lotField.addEventListener("change", confirmLot);
  // Enter also confirms on the phones whose keyboard only fires "change" when leaving the field.
  lotField.addEventListener("keydown", function (event) {
    if (event.key === "Enter") lotField.blur();
  });
  window.addEventListener("pagehide", stop);
  // "pagehide" stopped the camera, and a page restored from the back/forward cache runs nothing
  // again: without the reload, the screen would stay frozen, with no message.
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) window.location.reload();
  });
  window.addEventListener("resize", draw);
  if (!token) { showStatus(MESSAGES[401], true); return; }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showStatus(MESSAGES.camera, true);
    return;
  }
  navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } }).then(function (media) {
    stream = media;
    video.srcObject = media;
    timer = window.setInterval(tick, 1000 / FPS);
  }, function () { showStatus(MESSAGES.camera, true); });
})();
