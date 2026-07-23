## 2026-07-22T11:01:39Z
You are Worker 1 implementing Milestone 1 (R5 & R6).
Working directory: d:/talksync/talksync/.agents/teamwork_preview_worker_m1_1
Project root: d:/talksync/talksync

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your instructions:
1. Delete unused dead code files in `ui/widgets/`:
   - `ui/widgets/control_bar.py`
   - `ui/widgets/latency_badge.py`
   - `ui/widgets/sidebar.py`
   - `ui/widgets/status_indicator.py`
   - `ui/widgets/waveform.py`
2. Fix broken import in `services/translation/__init__.py`:
   - Remove invalid import `from translation.nllb import NLLBTranslator`.
3. Fix runtime callback signature mismatches & bugs in `ui/main_window.py`:
   - `_on_status`: Update signature to `_on_status(self, message: str, category: str = "info")` or `(self, message, category="info")` to match `pipeline.py`'s `on_status` emission.
   - `_on_latency`: Handle `latency_data` being either a `dict` (e.g. `{"avg_ms": float, ...}`) or a float, extracting `avg_ms` safely before passing to `self.status_bar.set_latency(...)`.
   - `_send_text_input`: Correctly schedule `self.pipeline.process_text_input(...)` on the pipeline's asyncio event loop using `asyncio.run_coroutine_threadsafe` (or `pipeline.submit_text_input(...)`).
4. Fix offline handling in `services/translation/argos.py`:
   - Catch exceptions around `argostranslate.package.update_package_index()` so offline / corporate proxy network blocks do not crash the app.
5. Fix `text_input_mode` property on `Pipeline` in `app/pipeline.py`:
   - Expose `@property def text_input_mode(self) -> bool: return self._text_mode`.
6. Run verification commands:
   - `python -c "from ui.main_window import MainWindow; print('OK')"`
   - Test importing all core modules.
7. Record changes, test output, and verification results in `d:/talksync/talksync/.agents/teamwork_preview_worker_m1_1/handoff.md`. Communicate back via message when finished.
