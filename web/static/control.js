(() => {
  const $ = (id) => document.getElementById(id);

  const els = {
    deviceSelect: $("deviceSelect"),
    sourceLang: $("sourceLang"),
    targetLang: $("targetLang"),
    whisperModel: $("whisperModel"),
    mtVendor: $("mtVendor"),
    glossary: $("glossary"),
    silenceThreshold: $("silenceThreshold"),
    settleBuffer: $("settleBuffer"),
    maxDuration: $("maxDuration"),
    minDuration: $("minDuration"),
    contextWindow: $("contextWindow"),
    fontSize: $("fontSize"),
    maxLines: $("maxLines"),
    textColor: $("textColor"),
    bgColor: $("bgColor"),
    showLiveIndicator: $("showLiveIndicator"),
    startStopBtn: $("startStopBtn"),
    displayLinkBtn: $("displayLinkBtn"),
    statusPill: $("statusPill"),
    statusText: $("statusText"),
    sourceFeed: $("sourceFeed"),
    translationFeed: $("translationFeed"),
    mainGrid: $("mainGrid"),
  };

  let running = false;
  let applyingRemoteConfig = false; // guard against PATCH-echo feedback loops

  // ---- glossary <-> textarea -------------------------------------------
  function glossaryToText(obj) {
    return Object.entries(obj || {}).map(([k, v]) => `${k}=${v}`).join("\n");
  }
  function textToGlossary(text) {
    const out = {};
    for (const line of text.split("\n")) {
      const idx = line.indexOf("=");
      if (idx > 0) {
        const k = line.slice(0, idx).trim();
        const v = line.slice(idx + 1).trim();
        if (k) out[k] = v;
      }
    }
    return out;
  }

  // ---- applying a full config snapshot to the UI ------------------------
  function applyConfig(cfg) {
    applyingRemoteConfig = true;
    els.sourceLang.value = cfg.pipeline.source_language;
    els.targetLang.value = cfg.pipeline.target_language;
    els.whisperModel.value = cfg.pipeline.whisper_model_size;
    els.mtVendor.value = cfg.pipeline.mt_vendor;
    els.glossary.value = glossaryToText(cfg.pipeline.glossary);
    if (cfg.pipeline.audio_device_index !== null && cfg.pipeline.audio_device_index !== undefined) {
      els.deviceSelect.value = String(cfg.pipeline.audio_device_index);
    }

    els.silenceThreshold.value = cfg.chunking.silence_threshold_ms;
    els.settleBuffer.value = cfg.chunking.settle_buffer_ms;
    els.maxDuration.value = cfg.chunking.max_chunk_duration_s;
    els.minDuration.value = cfg.chunking.min_chunk_duration_s;
    els.contextWindow.value = cfg.chunking.mt_context_window;

    els.fontSize.value = cfg.display.font_size_px;
    els.maxLines.value = cfg.display.max_lines;
    els.textColor.value = cfg.display.text_color;
    els.bgColor.value = cfg.display.background_color;
    els.showLiveIndicator.checked = cfg.display.show_live_indicator;

    updateSliderLabels();
    applyingRemoteConfig = false;
  }

  function updateSliderLabels() {
    $("silenceThresholdVal").textContent = `${els.silenceThreshold.value} ms`;
    $("settleBufferVal").textContent = `${els.settleBuffer.value} ms`;
    $("maxDurationVal").textContent = `${els.maxDuration.value} s`;
    $("minDurationVal").textContent = `${els.minDuration.value} s`;
    $("contextWindowVal").textContent = els.contextWindow.value;
    $("fontSizeVal").textContent = `${els.fontSize.value} px`;
    $("maxLinesVal").textContent = els.maxLines.value;
  }

  // ---- pushing a patch to the server, debounced for sliders --------------
  let patchTimer = null;
  function pushPatch(patch) {
    if (applyingRemoteConfig) return;
    clearTimeout(patchTimer);
    patchTimer = setTimeout(() => {
      fetch("/api/config", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      }).catch(() => {});
    }, 150);
  }

  function bindLive(el, path, transform) {
    el.addEventListener("input", () => {
      updateSliderLabels();
      const value = transform ? transform(el.value) : el.value;
      pushPatch({ [path[0]]: { [path[1]]: value } });
    });
  }

  bindLive(els.silenceThreshold, ["chunking", "silence_threshold_ms"], Number);
  bindLive(els.settleBuffer, ["chunking", "settle_buffer_ms"], Number);
  bindLive(els.maxDuration, ["chunking", "max_chunk_duration_s"], Number);
  bindLive(els.minDuration, ["chunking", "min_chunk_duration_s"], Number);
  bindLive(els.contextWindow, ["chunking", "mt_context_window"], Number);
  bindLive(els.fontSize, ["display", "font_size_px"], Number);
  bindLive(els.maxLines, ["display", "max_lines"], Number);
  bindLive(els.textColor, ["display", "text_color"]);
  bindLive(els.bgColor, ["display", "background_color"]);
  els.showLiveIndicator.addEventListener("change", () => {
    pushPatch({ display: { show_live_indicator: els.showLiveIndicator.checked } });
  });
  els.glossary.addEventListener("input", () => {
    pushPatch({ pipeline: { glossary: textToGlossary(els.glossary.value) } });
  });

  // setup fields only take effect on next Start — push immediately but no debounce concern
  for (const [el, field] of [
    [els.deviceSelect, "audio_device_index"],
    [els.sourceLang, "source_language"],
    [els.targetLang, "target_language"],
    [els.whisperModel, "whisper_model_size"],
    [els.mtVendor, "mt_vendor"],
  ]) {
    el.addEventListener("change", () => {
      if (applyingRemoteConfig) return;
      let value = el.value;
      if (field === "audio_device_index") value = value === "" ? null : Number(value);
      fetch("/api/config", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pipeline: { [field]: value } }),
      }).catch(() => {});
    });
  }

  // ---- devices -----------------------------------------------------------
  async function loadDevices() {
    const devices = await fetch("/api/devices").then((r) => r.json()).catch(() => []);
    els.deviceSelect.innerHTML = "";
    if (!devices.length) {
      const opt = document.createElement("option");
      opt.textContent = "No input devices found";
      opt.value = "";
      els.deviceSelect.appendChild(opt);
      return;
    }
    for (const d of devices) {
      const opt = document.createElement("option");
      opt.value = d.index;
      opt.textContent = `${d.name} (${d.channels}ch)`;
      els.deviceSelect.appendChild(opt);
    }
  }

  // ---- start/stop ----------------------------------------------------------
  function setLocked(locked) {
    els.mainGrid.classList.toggle("pipeline-locked", locked);
    els.startStopBtn.textContent = locked ? "Stop" : "Start";
    els.startStopBtn.classList.toggle("stop", locked);
  }

  els.startStopBtn.addEventListener("click", async () => {
    els.startStopBtn.disabled = true;
    try {
      if (!running) {
        await fetch("/api/start", { method: "POST" });
      } else {
        await fetch("/api/stop", { method: "POST" });
      }
    } finally {
      els.startStopBtn.disabled = false;
    }
  });

  els.displayLinkBtn.addEventListener("click", () => {
    window.open("/display", "_blank", "noopener");
  });

  function setStatus(state, message) {
    running = state === "listening";
    setLocked(running);
    els.statusPill.className = "status-pill" + (state === "listening" ? " listening" : "") + (state === "error" ? " error" : "");
    els.statusText.textContent = message || state;
  }

  // ---- feeds ---------------------------------------------------------------
  const MAX_FEED_ITEMS = 30;
  let partialEl = null;

  function clearEmpty(feed) {
    const empty = feed.querySelector(".feed-empty");
    if (empty) empty.remove();
  }

  function appendFeedItem(feed, text) {
    clearEmpty(feed);
    const div = document.createElement("div");
    div.className = "feed-entry";
    div.textContent = text;
    feed.appendChild(div);
    while (feed.children.length > MAX_FEED_ITEMS) feed.removeChild(feed.firstChild);
    feed.scrollTop = feed.scrollHeight;
  }

  function setPartial(text) {
    clearEmpty(els.sourceFeed);
    if (!partialEl) {
      partialEl = document.createElement("div");
      partialEl.className = "feed-entry partial";
      els.sourceFeed.appendChild(partialEl);
    }
    partialEl.textContent = text;
    els.sourceFeed.scrollTop = els.sourceFeed.scrollHeight;
  }

  function commitPartial(finalSourceText) {
    if (partialEl) {
      partialEl.remove();
      partialEl = null;
    }
    appendFeedItem(els.sourceFeed, finalSourceText);
  }

  // ---- websocket -------------------------------------------------------------
  function connectWS() {
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      if (msg.type === "config") {
        applyConfig(msg);
      } else if (msg.type === "status") {
        setStatus(msg.state, msg.message);
      } else if (msg.type === "partial_source") {
        setPartial(msg.text);
      } else if (msg.type === "committed") {
        commitPartial(msg.source_text);
        appendFeedItem(els.translationFeed, msg.translated_text);
      }
    };
    ws.onclose = () => setTimeout(connectWS, 1000);
  }

  (async () => {
    await loadDevices();
    connectWS();
  })();
})();
