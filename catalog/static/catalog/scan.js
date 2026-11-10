/* Phone barcode scan for the Add page.
   Prefers the browser's BarcodeDetector and falls back to the vendored
   ZXing build (@zxing/library 0.21.3). A hit fills #id_isbn and submits
   the existing form once. */
(function () {
  const form = document.getElementById("add-form");
  const isbnInput = document.getElementById("id_isbn");
  const openButton = document.getElementById("scan-open");
  const panel = document.getElementById("scan-panel");
  const video = document.getElementById("scan-video");
  const cancelButton = document.getElementById("scan-cancel");
  const status = document.getElementById("scan-status");

  if (!form || !isbnInput || !openButton || !panel || !video || !cancelButton || !status) return;

  const FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e"];
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d", { willReadFrequently: true });

  let stream = null;
  let timer = null;
  let session = 0;
  let running = false;
  let submitted = false;
  let lastRejected = "";
  let zxing = null;
  let zxingHints = null;

  function setStatus(text) {
    status.textContent = text;
  }

  function check13(first12) {
    let total = 0;
    for (let i = 0; i < 12; i++) total += Number(first12[i]) * (i % 2 === 0 ? 1 : 3);
    return String((10 - (total % 10)) % 10);
  }

  function check10(first9) {
    let total = 0;
    for (let i = 0; i < 9; i++) total += (10 - i) * Number(first9[i]);
    const check = (11 - (total % 11)) % 11;
    return check === 10 ? "X" : String(check);
  }

  /* Same acceptance rules as catalog/services/isbn.py. A 12-digit UPC is
     tried as an EAN-13 with a leading zero, which is how some decoders
     report a book barcode. */
  function normalizeIsbn(raw) {
    let value = String(raw || "").trim().replace(/^isbn(?:-1[03])?:?/i, "");
    value = value.replace(/[\s-]/g, "").toUpperCase();
    if (/^\d{12}$/.test(value)) value = "0" + value;
    if (/^\d{13}$/.test(value) && check13(value.slice(0, 12)) === value[12]) return value;
    if (/^\d{9}[\dX]$/.test(value) && check10(value.slice(0, 9)) === value[9]) {
      const body = "978" + value.slice(0, 9);
      return body + check13(body);
    }
    return null;
  }

  function stopTracks(media) {
    if (!media) return;
    media.getTracks().forEach((track) => track.stop());
  }

  function stopCamera() {
    session += 1;
    running = false;
    if (timer) clearTimeout(timer);
    timer = null;
    stopTracks(stream);
    stream = null;
    video.srcObject = null;
  }

  function hidePanel() {
    panel.hidden = true;
    openButton.disabled = false;
    setStatus("");
    lastRejected = "";
  }

  function consider(raw) {
    const isbn = normalizeIsbn(raw);
    if (!isbn) {
      if (raw !== lastRejected) {
        lastRejected = String(raw);
        setStatus("That isn’t an ISBN. Hold the barcode steady.");
      }
      return false;
    }
    if (submitted) return true;
    submitted = true;
    isbnInput.value = isbn;
    stopCamera();
    if (typeof form.requestSubmit === "function") form.requestSubmit();
    else form.submit();
    return true;
  }

  async function nativeDetector() {
    if (!("BarcodeDetector" in window)) return null;
    try {
      const supported = await BarcodeDetector.getSupportedFormats();
      const formats = FORMATS.filter((format) => supported.includes(format));
      if (!formats.length) return null;
      return new BarcodeDetector({ formats });
    } catch (err) {
      return null;
    }
  }

  function loadZxing() {
    if (window.ZXing) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = openButton.dataset.zxing;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error("zxing"));
      document.head.appendChild(script);
    });
  }

  function zxingReader() {
    const hints = new Map();
    hints.set(ZXing.DecodeHintType.POSSIBLE_FORMATS, [
      ZXing.BarcodeFormat.EAN_13,
      ZXing.BarcodeFormat.EAN_8,
      ZXing.BarcodeFormat.UPC_A,
      ZXing.BarcodeFormat.UPC_E,
    ]);
    zxingHints = hints;
    zxing = new ZXing.MultiFormatReader();
    zxing.setHints(hints);
  }

  function decodeWithZxing() {
    if (!zxing || !video.videoWidth) return null;
    const scale = Math.min(1, 800 / video.videoWidth);
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    try {
      const source = new ZXing.HTMLCanvasElementLuminanceSource(canvas);
      const bitmap = new ZXing.BinaryBitmap(new ZXing.HybridBinarizer(source));
      const result = zxing.decode(bitmap, zxingHints);
      const text = typeof result.getText === "function" ? result.getText() : result.text;
      zxing.reset();
      return text || null;
    } catch (err) {
      try { zxing.reset(); } catch (e) { /* reader may already be clear */ }
      return null;
    }
  }

  async function scanLoop(detector) {
    if (!running || submitted) return;
    if (video.readyState >= 2) {
      try {
        if (detector) {
          const codes = await detector.detect(video);
          for (const code of codes) {
            if (consider(code.rawValue)) return;
          }
        } else {
          const text = decodeWithZxing();
          if (text && consider(text)) return;
        }
      } catch (err) {
        /* A frame with no barcode is normal. */
      }
    }
    if (running && !submitted) timer = setTimeout(() => scanLoop(detector), 200);
  }

  openButton.addEventListener("click", async () => {
    if (running) return;
    panel.hidden = false;
    submitted = false;
    lastRejected = "";
    if (!window.isSecureContext) {
      setStatus("The camera needs HTTPS. Open Stacks at its https address.");
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus("This browser can’t open the camera. Type the ISBN instead.");
      return;
    }
    openButton.disabled = true;
    setStatus("Starting the camera…");
    const mine = session;
    try {
      const media = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      if (mine !== session) {
        stopTracks(media);
        return;
      }
      stream = media;
      video.srcObject = stream;
      await video.play();
      if (mine !== session) {
        stopCamera();
        return;
      }
      let detector = await nativeDetector();
      if (mine !== session) {
        stopCamera();
        return;
      }
      if (!detector) {
        await loadZxing();
        if (mine !== session) {
          stopCamera();
          return;
        }
        if (!window.ZXing) throw new Error("zxing");
        zxingReader();
      }
      if (mine !== session) {
        stopCamera();
        return;
      }
      running = true;
      setStatus("Point the camera at the barcode.");
      scanLoop(detector);
    } catch (err) {
      if (mine !== session) return;
      const cameraStarted = !!stream;
      stopCamera();
      openButton.disabled = false;
      setStatus(cameraStarted
        ? "This browser can’t read barcodes. Type the ISBN instead."
        : "The camera didn’t start. Allow camera access, or type the ISBN.");
    }
  });

  cancelButton.addEventListener("click", () => {
    stopCamera();
    hidePanel();
  });

  window.addEventListener("pagehide", stopCamera);
})();
