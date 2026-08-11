/**
 * TalkSync AI — Web UI State Manager & IPC Bridge Handler
 */
(function () {
    "use strict";

    const state = {
        active: false,
        sourceLang: "EN",
        targetLang: "HI",
        mode: "2-way",
        micMuted: false,
        ttsEnabledA: true,
        ttsEnabledB: true,
        audioSettings: {
            vadThreshold: 0.5,
            rmsGate: 0.0003,
            loopback_enabled: true,
        },
        keywords: []
    };

    const TalkSyncUI = {
        // --- Initialization ---
        init: function () {
            console.log("[TalkSyncUI] Initializing Web UI State Manager...");
            window.addEventListener("pywebviewready", () => {
                console.log("[TalkSyncUI] PyWebView Ready!");
                this.syncSettingsFromBackend();
            });

            // Fallback sync if pywebview is already loaded
            if (window.pywebview && window.pywebview.api) {
                this.syncSettingsFromBackend();
            }

            // Wire DOM Event Listeners
            const srcSelect = document.getElementById("select-source-lang");
            if (srcSelect) {
                srcSelect.addEventListener("change", (e) => {
                    state.sourceLang = e.target.value;
                    this.updateLanguages();
                });
            }

            const tgtSelect = document.getElementById("select-target-lang");
            if (tgtSelect) {
                tgtSelect.addEventListener("change", (e) => {
                    state.targetLang = e.target.value;
                    this.updateLanguages();
                });
            }
        },

        syncSettingsFromBackend: function () {
            if (!window.pywebview || !window.pywebview.api) return;

            window.pywebview.api.get_settings().then((cfg) => {
                if (!cfg) return;
                state.sourceLang = cfg.source_lang || "EN";
                state.targetLang = cfg.target_lang || "HI";
                state.mode = cfg.translation_mode || "2-way";
                state.micMuted = !!cfg.mic_muted;
                state.ttsEnabledA = cfg.tts_enabled_a !== false;
                state.ttsEnabledB = cfg.tts_enabled_b !== false;
                state.theme = cfg.theme || "light";
                state.audioSettings = cfg.audio_settings || {};
                state.keywords = cfg.keywords || [];

                // Apply theme class to body
                const body = document.body;
                if (body) {
                    body.className = (state.theme === "light") ? "theme-light" : "bg-dark theme-dark";
                }

                // Sync DOM
                const srcSelect = document.getElementById("select-source-lang");
                const tgtSelect = document.getElementById("select-target-lang");
                const badgeA = document.getElementById("badge-lang-a");
                const badgeB = document.getElementById("badge-lang-b");

                if (srcSelect) srcSelect.value = state.sourceLang;
                if (tgtSelect) tgtSelect.value = state.targetLang;
                if (badgeA) badgeA.innerText = state.sourceLang;
                if (badgeB) badgeB.innerText = state.targetLang;

                this.setMode(state.mode);
                this.updateMicUI();
                this.updateTtsUI();
            }).catch(err => console.error("[TalkSyncUI] get_settings error:", err));
        },

        // --- JS-to-Python IPC Triggers ---
        toggleSession: function () {
            if (!window.pywebview || !window.pywebview.api) {
                console.warn("[TalkSyncUI] pywebview.api not ready, using simulated fallback state.");
                state.active = !state.active;
                this.updateSessionUI(state.active);
                return;
            }

            if (!state.active) {
                const loopbackVal = state.audioSettings.loopback_enabled !== false;
                window.pywebview.api.start_session(state.sourceLang, state.targetLang, loopbackVal, false)
                    .then((res) => {
                        state.active = true;
                        this.updateSessionUI(true);
                    }).catch(err => {
                        console.error("[TalkSyncUI] start_session error:", err);
                        state.active = true;
                        this.updateSessionUI(true);
                    });
            } else {
                window.pywebview.api.stop_session()
                    .then((res) => {
                        state.active = false;
                        this.updateSessionUI(false);
                    }).catch(err => {
                        console.error("[TalkSyncUI] stop_session error:", err);
                        state.active = false;
                        this.updateSessionUI(false);
                    });
            }
        },

        startSession: function (source, target, loopback, textMode) {
            state.sourceLang = source || state.sourceLang;
            state.targetLang = target || state.targetLang;
            if (window.pywebview && window.pywebview.api) {
                return window.pywebview.api.start_session(state.sourceLang, state.targetLang, !!loopback, !!textMode);
            }
            state.active = true;
            this.updateSessionUI(true);
            return Promise.resolve({ status: "ok", active: true });
        },

        stopSession: function () {
            if (window.pywebview && window.pywebview.api) {
                return window.pywebview.api.stop_session();
            }
            state.active = false;
            this.updateSessionUI(false);
            return Promise.resolve({ status: "ok", active: false });
        },

        updateLanguages: function () {
            const badgeA = document.getElementById("badge-lang-a");
            const badgeB = document.getElementById("badge-lang-b");
            if (badgeA) badgeA.innerText = state.sourceLang;
            if (badgeB) badgeB.innerText = state.targetLang;

            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.set_languages(state.sourceLang, state.targetLang);
            }
        },

        setLanguages: function (source, target) {
            state.sourceLang = source;
            state.targetLang = target;
            this.updateLanguages();
        },

        setMode: function (mode) {
            state.mode = mode;
            const grid = document.getElementById("transcript-grid");
            const btn2 = document.getElementById("btn-mode-2way");
            const btn1 = document.getElementById("btn-mode-1way");
            const panelB = document.getElementById("panel-b");

            if (mode === "1-way" || mode === "one_way") {
                if (grid) grid.className = "transcript-grid mode-1way";
                if (panelB) panelB.style.display = "none";
                if (btn1) btn1.classList.add("active");
                if (btn2) btn2.classList.remove("active");
            } else {
                if (grid) grid.className = "transcript-grid mode-2way";
                if (panelB) panelB.style.display = "flex";
                if (btn2) btn2.classList.add("active");
                if (btn1) btn1.classList.remove("active");
            }

            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.set_translation_mode(mode);
            }
        },

        setTranslationMode: function (mode) {
            this.setMode(mode);
        },

        toggleMicMute: function () {
            state.micMuted = !state.micMuted;
            this.updateMicUI();
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.toggle_mic_mute(state.micMuted);
            }
        },

        togglePanelTTS: function (panel) {
            if (panel === "A" || panel === "a") {
                state.ttsEnabledA = !state.ttsEnabledA;
            } else {
                state.ttsEnabledB = !state.ttsEnabledB;
            }
            this.updateTtsUI();

            if (window.pywebview && window.pywebview.api) {
                const p = (panel === "A" || panel === "a") ? "A" : "B";
                const enabled = (p === "A") ? state.ttsEnabledA : state.ttsEnabledB;
                window.pywebview.api.set_panel_tts(p, enabled);
            }
        },

        setPanelTTS: function (panel, enabled) {
            if (panel === "A" || panel === "a") {
                state.ttsEnabledA = !!enabled;
            } else {
                state.ttsEnabledB = !!enabled;
            }
            this.updateTtsUI();
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.set_panel_tts(panel, enabled);
            }
        },

        submitText: function () {
            const input = document.getElementById("text-input-field");
            if (!input) return;
            const val = input.value.trim();
            if (!val) return;

            input.value = "";
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.submit_text_input(val, state.targetLang);
            }
        },

        submitTextInput: function (text, targetLang) {
            if (window.pywebview && window.pywebview.api) {
                return window.pywebview.api.submit_text_input(text, targetLang || state.targetLang);
            }
            return Promise.resolve({ status: "ok", original: text, translated: `Translated[${text}]` });
        },

        handleTextKeyPress: function (e) {
            if (e.key === "Enter") this.submitText();
        },

        // --- UI Updates ---
        updateSessionUI: function (active) {
            const btn = document.getElementById("btn-session-toggle");
            const icon = document.getElementById("session-btn-icon");
            const text = document.getElementById("session-btn-text");

            if (active) {
                if (btn) btn.className = "btn-primary btn-stop";
                if (icon) icon.innerText = "■";
                if (text) text.innerText = "STOP SESSION";
                this.onStatus({ status: "RUNNING", active: true });
            } else {
                if (btn) btn.className = "btn-primary btn-start";
                if (icon) icon.innerText = "▶";
                if (text) text.innerText = "START SESSION";
                this.onStatus({ status: "STOPPED", active: false });
            }
        },

        updateMicUI: function () {
            const btn = document.getElementById("btn-mic-toggle");
            const icon = document.getElementById("mic-icon");
            if (!btn) return;
            if (state.micMuted) {
                btn.classList.add("muted");
                if (icon) icon.innerText = "🔇";
            } else {
                btn.classList.remove("muted");
                if (icon) icon.innerText = "🎤";
            }
        },

        updateTtsUI: function () {
            const btnA = document.getElementById("btn-tts-a");
            const btnB = document.getElementById("btn-tts-b");

            if (btnA) btnA.className = state.ttsEnabledA ? "btn-toggle-active" : "btn-toggle-disabled";
            if (btnB) btnB.className = state.ttsEnabledB ? "btn-toggle-active" : "btn-toggle-disabled";
        },

        // --- Python-to-JS Callback Handlers (Targeted by evaluate_js) ---
        onTranscription: function (data) {
            if (!data) return;
            const speaker = (data.speaker || data.input_source || "user").toLowerCase();
            const isB = speaker === "loopback" || speaker === "computer_audio" || speaker === "remote" || speaker === "speaker_b" || speaker === "b" || speaker === "speaker_2";
            const panelSuffix = isB ? "b" : "a";

            const streamingBox = document.getElementById(`streaming-${panelSuffix}`);
            const streamingText = document.getElementById(`streaming-text-${panelSuffix}`);

            if (!streamingBox || !streamingText) return;

            if (!data.is_final) {
                streamingBox.classList.remove("empty");
                streamingText.setAttribute("data-original", data.text || "");
                // Show original + any pending translation
                const pending = streamingText.getAttribute("data-translated") || "";
                streamingText.innerText = pending
                    ? `${data.text} → ${pending}`
                    : (data.text || "");
            } else {
                streamingBox.classList.add("empty");
                streamingText.innerText = "";
                streamingText.removeAttribute("data-original");
                streamingText.removeAttribute("data-translated");
            }
        },

        onTranslation: function (data) {
            if (!data) return;
            const speaker = (data.speaker || data.input_source || "user").toLowerCase();
            const isB = speaker === "loopback" || speaker === "computer_audio" || speaker === "remote" || speaker === "speaker_b" || speaker === "b" || speaker === "speaker_2";
            const panelSuffix = isB ? "b" : "a";
            const list = document.getElementById(`history-list-${panelSuffix}`);
            const streamingText = document.getElementById(`streaming-text-${panelSuffix}`);
            const streamingBox = document.getElementById(`streaming-${panelSuffix}`);

            const orig = data.original || data.original_text || "";
            const trans = data.translated || data.translated_text || "";

            if (data.is_final === false) {
                // Real-time streaming: update the streaming box with live translation
                if (streamingBox && streamingText) {
                    streamingBox.classList.remove("empty");
                    streamingText.setAttribute("data-translated", trans);
                    const origLive = streamingText.getAttribute("data-original") || orig;
                    streamingText.innerText = trans ? `${origLive} → ${trans}` : origLive;
                }
            } else {
                // Final: clear streaming box, append card to history
                if (streamingBox && streamingText) {
                    streamingBox.classList.add("empty");
                    streamingText.innerText = "";
                    streamingText.removeAttribute("data-original");
                    streamingText.removeAttribute("data-translated");
                }
                if (list && orig) {
                    const card = document.createElement("div");
                    card.className = "segment-card";
                    const ts = new Date().toLocaleTimeString();
                    card.innerHTML = `
                        <div class="card-timestamp">${ts}</div>
                        <div class="original-text">${orig}</div>
                        <div class="translated-text">${trans}</div>
                    `;
                    list.prepend(card);
                }
            }
        },

        onStatus: function (data) {
            if (!data) return;
            const badge = document.getElementById("status-badge");
            const text = document.getElementById("status-text");
            const statusStr = (data.status || "STOPPED").toUpperCase();

            if (text) text.innerText = statusStr;
            if (badge) {
                const isRunning = data.active || statusStr === "RUNNING" || statusStr === "ACTIVE";
                badge.className = `badge status-${isRunning ? "running" : "stopped"}`;
            }
        },

        onLatency: function (data) {
            if (!data) return;
            const stt = document.getElementById("lat-stt");
            const trans = document.getElementById("lat-trans");
            const tts = document.getElementById("lat-tts");
            const total = document.getElementById("lat-total");

            if (stt) stt.innerText = `${Math.round(data.stt_ms || 0)}ms`;
            if (trans) trans.innerText = `${Math.round(data.translation_ms || 0)}ms`;
            if (tts) tts.innerText = `${Math.round(data.tts_ms || 0)}ms`;
            if (total) total.innerText = `${Math.round(data.total_ms || 0)}ms`;
        },

        onAudioLevel: function (data) {
            if (!data && data !== 0) return;
            const level = typeof data === "number" ? data : (data.level || 0);
            const rms = typeof data === "object" ? (data.rms || 0) : 0;

            if (window.WaveformVisualizer) {
                window.WaveformVisualizer.draw(level, rms);
            }
        },

        onVADState: function (data) {
            if (!data) return;
            const pill = document.getElementById("vad-indicator");
            const text = document.getElementById("vad-text");
            const isSpeech = typeof data === "boolean" ? data : !!data.is_speech;

            if (pill && text) {
                if (isSpeech) {
                    pill.className = "vad-pill active";
                    text.innerText = "SPEECH DETECTED";
                } else {
                    pill.className = "vad-pill inactive";
                    text.innerText = "SILENCE";
                }
            }
        },

        // --- Modal Control Helpers ---
        toggleSettingsModal: function (show) {
            const modal = document.getElementById("settings-modal");
            if (!modal) return;
            modal.className = show ? "modal-overlay" : "modal-overlay hidden";

            if (show) {
                // Populate sliders and inputs
                const vadElem = document.getElementById("setting-vad-thresh");
                const rmsElem = document.getElementById("setting-rms-gate");
                const vadVal = document.getElementById("vad-val");
                const rmsVal = document.getElementById("rms-val");
                const kwElem = document.getElementById("setting-keywords");
                const loopbackCheck = document.getElementById("setting-loopback");
                const virtualMicCheck = document.getElementById("setting-virtual-mic");

                const vadThresh = state.audioSettings.vad_threshold !== undefined ? state.audioSettings.vad_threshold : 0.5;
                const rmsGate = state.audioSettings.rms_gate !== undefined ? state.audioSettings.rms_gate : 0.0003;

                if (vadElem) { vadElem.value = vadThresh; }
                if (vadVal) { vadVal.innerText = Number(vadThresh).toFixed(2); }
                if (rmsElem) { rmsElem.value = rmsGate; }
                if (rmsVal) { rmsVal.innerText = Number(rmsGate).toFixed(4); }
                if (kwElem) { kwElem.value = (state.keywords || []).join(", "); }
                
                if (loopbackCheck) { loopbackCheck.checked = !!state.audioSettings.loopback_enabled; }
                if (virtualMicCheck) { virtualMicCheck.checked = !!state.audioSettings.virtual_mic_enabled; }

                // Fetch and populate device lists dynamically
                if (window.pywebview && window.pywebview.api) {
                    window.pywebview.api.list_audio_devices().then((res) => {
                        if (!res) return;
                        const inputSelect = document.getElementById("select-audio-input");
                        const outputSelect = document.getElementById("select-audio-output");

                        if (inputSelect) {
                            inputSelect.innerHTML = '<option value="default">Default Input Microphone</option>';
                            (res.inputs || []).forEach((dev) => {
                                const opt = document.createElement("option");
                                opt.value = dev.id;
                                opt.innerText = `${dev.name} (${dev.channels} ch)`;
                                inputSelect.appendChild(opt);
                            });
                            // Preselect active device ID
                            if (state.audioSettings.input_device_id !== undefined && state.audioSettings.input_device_id !== null) {
                                inputSelect.value = state.audioSettings.input_device_id;
                            } else {
                                inputSelect.value = "default";
                            }
                        }

                        if (outputSelect) {
                            outputSelect.innerHTML = '<option value="default">Default Output Speaker</option>';
                            (res.outputs || []).forEach((dev) => {
                                const opt = document.createElement("option");
                                opt.value = dev.id;
                                opt.innerText = `${dev.name} (${dev.channels} ch)`;
                                outputSelect.appendChild(opt);
                            });
                            // Preselect active device ID
                            if (state.audioSettings.output_device_id !== undefined && state.audioSettings.output_device_id !== null) {
                                outputSelect.value = state.audioSettings.output_device_id;
                            } else {
                                outputSelect.value = "default";
                            }
                        }
                    }).catch(err => console.error("[TalkSyncUI] list_audio_devices error:", err));
                }
            }
        },

        toggleHistoryModal: function (show) {
            const modal = document.getElementById("history-modal");
            if (modal) {
                modal.className = show ? "modal-overlay" : "modal-overlay hidden";
                if (show) this.loadHistory();
            }
        },

        onModalOverlayClick: function (e, id) {
            if (e.target.id === id) {
                this.toggleSettingsModal(false);
                this.toggleHistoryModal(false);
            }
        },

        saveSettings: function () {
            const vadElem = document.getElementById("setting-vad-thresh");
            const rmsElem = document.getElementById("setting-rms-gate");
            const kwElem = document.getElementById("setting-keywords");
            const inputSelect = document.getElementById("select-audio-input");
            const outputSelect = document.getElementById("select-audio-output");
            const loopbackCheck = document.getElementById("setting-loopback");
            const virtualMicCheck = document.getElementById("setting-virtual-mic");

            const vad = vadElem ? parseFloat(vadElem.value) : 0.5;
            const rms = rmsElem ? parseFloat(rmsElem.value) : 0.0003;
            const kw = kwElem ? kwElem.value.split(",").map(s => s.trim()).filter(Boolean) : [];

            let inputId = null;
            if (inputSelect && inputSelect.value !== "default") {
                inputId = parseInt(inputSelect.value);
            }
            let outputId = null;
            if (outputSelect && outputSelect.value !== "default") {
                outputId = parseInt(outputSelect.value);
            }

            const loopbackEnabled = loopbackCheck ? !!loopbackCheck.checked : false;
            const virtualMicEnabled = virtualMicCheck ? !!virtualMicCheck.checked : false;

            const newSettings = {
                vad_threshold: vad,
                rms_gate: rms,
                input_device_id: inputId,
                output_device_id: outputId,
                loopback_enabled: loopbackEnabled,
                virtual_mic_enabled: virtualMicEnabled
            };

            // Store back to local state
            state.audioSettings = newSettings;
            state.keywords = kw;

            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.set_audio_settings(newSettings)
                    .then(() => {
                        return window.pywebview.api.update_keywords(kw);
                    })
                    .then(() => {
                        console.log("[TalkSyncUI] Settings saved successfully on Python backend");
                    })
                    .catch(err => console.error("[TalkSyncUI] Error saving settings:", err));
            }
            this.toggleSettingsModal(false);
        },

        fetchHistory: function (limit) {
            if (window.pywebview && window.pywebview.api) {
                return window.pywebview.api.fetch_history(limit || 50);
            }
            return Promise.resolve([]);
        },

        loadHistory: function () {
            if (!window.pywebview || !window.pywebview.api) return;

            window.pywebview.api.fetch_history(50).then((items) => {
                const list = document.getElementById("history-modal-list");
                if (!list) return;
                if (!items || items.length === 0) {
                    list.innerHTML = '<p class="empty-state">No past session history found.</p>';
                    return;
                }

                list.innerHTML = items.map(item => `
                    <div class="segment-card">
                        <div style="font-size: 11px; color: var(--text-dim);">${item.timestamp} [${item.source_lang} ➔ ${item.target_lang}]</div>
                        <div class="original-text">${item.original}</div>
                        <div class="translated-text">${item.translated}</div>
                    </div>
                `).join("");
            }).catch(err => console.error("[TalkSyncUI] loadHistory error:", err));
        }
    };

    window.TalkSyncUI = TalkSyncUI;
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => TalkSyncUI.init());
    } else {
        TalkSyncUI.init();
    }
})();
