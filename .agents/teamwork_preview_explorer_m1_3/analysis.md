# Analysis Report — Milestone 1 (R5 & R6) Codebase Investigation

## Summary of Core Findings
Static analysis and dry-run inspection of `main.py`, `app/application.py`, `app/pipeline.py`, `ui/main_window.py`, and supporting services revealed **5 critical runtime bugs/failures**, along with verified compliance for previous GPU memory and PiperVoice lessons:

1. **Callback Signature Mismatch (`on_status`)**: `app/pipeline.py` passes 2 arguments (`status_msg`, `status_type`) to `self.on_status()`, but `ui/main_window.py`'s `_on_status()` only accepts 1 argument (`status: str`), causing `TypeError` on pipeline state change.
2. **Callback Type Mismatch (`on_latency`)**: `app/pipeline.py` passes a `dict` to `self.on_latency()`, while `ui/main_window.py` passes it to `StatusBar.set_latency()`, which attempts `f"Latency: {latency_ms:.0f}ms"` on a `dict`, causing a string formatting `TypeError`.
3. **Unawaited Coroutine Bug (`process_text_input`)**: `ui/main_window.py` calls `self.pipeline.process_text_input(...)` synchronously from GUI thread. Because `process_text_input` in `app/pipeline.py` is `async def`, the coroutine is never scheduled or awaited, generating a `RuntimeWarning` and failing text translation.
4. **Argos Translation Network Dependency Failure**: `services/translation/argos.py` calls `argostranslate.package.update_package_index()` and `pkg.download()`, which fail in offline/corporate proxy environments.
5. **Startup Exception on Unhandled Translation Engine Failure**: `services/translation/factory.py` throws `RuntimeError("No translation engine available")` when both Argos and DeepL fail, causing `app.build_pipeline()` in `main.py` to crash application startup.

---

## Detailed Evidence Chains

### 1. `on_status` Callback Signature Mismatch
* **Observation**:
  - `app/pipeline.py` lines 106, 116, 122, 131, 136, 224, 252, 340, 395:
    ```python
    self.on_status("Starting audio...", "processing")
    self.on_status("Listening...", "listening")
    self.on_status("Translating...", "translating")
    ```
  - `ui/main_window.py` line 439:
    ```python
    def _on_status(self, status: str) -> None:
        self.after(0, lambda: self.status_bar.set_status(status))
    ```
* **Logic Chain**:
  - `pipeline.py` invokes `on_status` with two positional string arguments: `message` and `category`.
  - `main_window.py` registers `self.pipeline.on_status = self._on_status`.
  - Python attempts to bind `(self, status)` with 2 passed arguments, resulting in `TypeError: MainWindow._on_status() takes 2 positional arguments but 3 were given`.
* **Fix Proposal**: Update `_on_status(self, status: str, category: str = "")` in `ui/main_window.py`.

---

### 2. `on_latency` Data Format Mismatch
* **Observation**:
  - `app/pipeline.py` line 445:
    ```python
    overall_avg = sum(s["avg_ms"] for s in summaries.values()) / len(summaries)
    self.on_latency({"avg_ms": overall_avg, "stages": summaries})
    ```
  - `ui/main_window.py` line 442:
    ```python
    def _on_latency(self, latency_ms: float) -> None:
        self.after(0, lambda: self.status_bar.set_latency(latency_ms))
    ```
  - `ui/widgets/status_bar.py` line 33:
    ```python
    def set_latency(self, latency_ms: float) -> None:
        self.lbl_latency.configure(text=f"Latency: {latency_ms:.0f}ms")
    ```
* **Logic Chain**:
  - `pipeline.py` sends a dictionary containing overall and per-stage latency data to `on_latency`.
  - `main_window.py` passes the raw `dict` to `set_latency`.
  - `set_latency` executes float formatting `f"Latency: {dict:.0f}ms"`, raising `TypeError: unsupported format string passed to dict.__format__`.
* **Fix Proposal**: Extract `avg_ms` from `dict` inside `_on_latency`:
  ```python
  val = latency_data.get("avg_ms", 0.0) if isinstance(latency_data, dict) else float(latency_data)
  ```

---

### 3. Text Input Coroutine Unawaited
* **Observation**:
  - `app/pipeline.py` line 452:
    ```python
    async def process_text_input(self, text: str, source_lang: Optional[str] = None) -> None:
    ```
  - `ui/main_window.py` line 385:
    ```python
    if hasattr(self.pipeline, "process_text_input"):
        self.pipeline.process_text_input(text=text, source_lang=self._source_lang)
    ```
* **Logic Chain**:
  - `process_text_input` is defined as an asynchronous coroutine function (`async def`).
  - `_send_text_input` in `main_window.py` calls `self.pipeline.process_text_input(...)` synchronously without `await` or thread-safe scheduling on the pipeline event loop.
  - Python creates an unawaited coroutine object, emits `RuntimeWarning: coroutine 'Pipeline.process_text_input' was never awaited`, and no text translation occurs.
* **Fix Proposal**: Use `asyncio.run_coroutine_threadsafe(self.pipeline.process_text_input(text, self._source_lang), self.pipeline._loop)` when `self.pipeline._loop` is running.

---

### 4. Argos Translator Online Package Update Failure
* **Observation**:
  - `services/translation/argos.py` lines 21-25:
    ```python
    argostranslate.package.update_package_index()
    available = argostranslate.package.get_available_packages()
    for pkg in available:
        if pkg.from_code == "en" and pkg.to_code == "hi":
            argostranslate.package.install_from_path(pkg.download())
    ```
* **Logic Chain**:
  - Under corporate proxy/offline environment constraints, outbound connections to HuggingFace / Argos index servers are blocked.
  - `update_package_index()` throws a network connection exception.
  - `ArgosTranslator.start()` catches the exception and re-raises (`raise`), causing `TranslationFactory` to fail loading Argos.
* **Fix Proposal**: Check `argostranslate.translate.get_installed_languages()` first and use already installed packages offline before attempting online downloads.

---

### 5. Startup Crash on Missing Translation Engine
* **Observation**:
  - `services/translation/factory.py` line 31:
    ```python
    raise RuntimeError("No translation engine available")
    ```
  - `app/application.py` line 52:
    ```python
    translator = asyncio.run(TranslationFactory.create(self.settings))
    ```
* **Logic Chain**:
  - When both Argos and DeepL fail (e.g. offline + missing DeepL API key), `TranslationFactory.create` raises `RuntimeError`.
  - `app.build_pipeline()` in `main.py` executes `asyncio.run(...)` during initialization, unhandled exception bubbles up and crashes application startup.
* **Fix Proposal**: Provide a `FallbackTranslator` (Passthrough / Mock) in `TranslationFactory` so the UI and application can start gracefully with a user notification.

---

## Verification of Lessons from Previous Failures

| Lesson / Area | Location Inspected | Status | Finding Details |
|---|---|---|---|
| `torch.cuda.get_device_properties(0).total_memory` | `services/diagnostics/monitor.py:38, 49` | ✅ Compliant | Code uses `props.total_memory` (not `total_mem`). |
| `PiperVoice.load(model_path, config_path, use_cuda=False)` | `services/tts/piper.py:37` | ✅ Compliant | Correct API call used; no `piper.download` imported. |
| `customtkinter.CTkTextbox` tag configuration | `ui/widgets/transcript_panel.py:135` | ✅ Compliant | Obtains `raw_text = self.textbox._textbox` (underlying Tkinter `Text`) before configuring tags. |
| `HistoryDatabase.delete_session()` | `services/history/database.py:94` | ✅ Compliant | `delete_session` method implemented for CRUD operations. |
| Attribute `text_input_mode` | `ui/main_window.py:371` vs `app/pipeline.py:69` | ⚠️ Discrepancy | `main_window.py` checks `hasattr(self.pipeline, "text_input_mode")`, but `Pipeline` names it `_text_mode`. |

---

## Recommended Next Steps for Implementers
1. Fix callback parameter signatures in `ui/main_window.py` (`_on_status` and `_on_latency`).
2. Wrap `process_text_input` in `asyncio.run_coroutine_threadsafe` inside `_send_text_input`.
3. Update `services/translation/argos.py` to support offline pre-installed model detection.
4. Add a safe fallback translator in `services/translation/factory.py` to prevent startup crashes.
5. Standardize `text_input_mode` property on `Pipeline`.
