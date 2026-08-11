## 2026-08-05T21:22:50Z
Objective: Fix DeepL Slow Startup in `services/translation/deepl.py`.
Requirements:
1. Currently `services/translation/deepl.py` tries a corporate proxy (`192.168.0.1:8090`) with 5 retries (~25s) before falling back to direct connection.
2. Implement a fast single socket connectivity check (1s timeout) to the proxy endpoint. If unreachable or times out, immediately fallback to direct connection without performing 5 slow retries.
3. Do NOT remove proxy support — just make the failure fast.
4. Verify that DeepL initializes within 3-5 seconds cleanly.
5. Run Python tests or a test snippet to verify initialization speed and functionality.
