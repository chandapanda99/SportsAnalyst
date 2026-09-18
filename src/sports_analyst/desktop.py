# ruff: noqa: E501
from __future__ import annotations

import argparse
import base64
import multiprocessing
import os
import socket
import sys
import threading
import time
import urllib.request
from contextlib import suppress
from pathlib import Path
from typing import Any

from sports_analyst.desktop_config import DesktopConfigStore


def _run_desktop_worker(settings: Any, stop_event: Any) -> None:
    """Process target kept at module scope for Windows spawn/PyInstaller."""
    from sports_analyst.worker import run_worker

    run_worker(settings, stop_event=stop_event)


def _setup_icon_data_uri() -> str:
    """Embed the product logo because the setup page is shown before the web server starts."""
    candidates = []
    if bundle_root := getattr(sys, "_MEIPASS", None):
        candidates.append(Path(bundle_root) / "frontend" / "dist" / "favicon.svg")
    candidates.append(Path(__file__).resolve().parents[2] / "frontend" / "public" / "favicon.svg")
    for candidate in candidates:
        if candidate.is_file():
            encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
            return f"data:image/svg+xml;base64,{encoded}"
    return ""


SETUP_ICON_DATA_URI = _setup_icon_data_uri()

SETUP_HTML = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Open Sports Analyst Setup</title><style>
:root{color-scheme:dark;font-family:Inter,Segoe UI,sans-serif;background:#06131f;color:#edf7ff}
*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:32px;background:radial-gradient(circle at 80% 0,#15394a 0,transparent 38%),#06131f}
main{width:min(820px,100%);border:1px solid #29495d;background:#0a1c2c;padding:34px;box-shadow:0 24px 80px #0008}
.eyebrow{color:#68e0c3;font:12px Consolas,monospace;letter-spacing:.14em}.heading{display:flex;gap:18px;align-items:center;margin-bottom:28px}.mark{width:58px;height:58px}
h1{font-size:29px;margin:5px 0 3px}p{color:#a7bfd0;line-height:1.5;margin:0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:15px;margin:26px 0}
label{display:grid;gap:6px;color:#d7e5ee;font-size:12px}.wide{grid-column:1/-1}.provider-fields{display:contents}.field-name{display:flex;align-items:baseline;gap:6px}.required{color:#68e0c3;font-weight:700}.optional{color:#829cab;font-weight:400}.hint{color:#8faaba;font-size:11px;line-height:1.45;margin-top:-1px}.field-key .hint{color:#b9cbd5}.form-note{grid-column:1/-1;color:#8faaba;font-size:11px;margin:-3px 0 0}.form-note .required{margin-right:3px}input,select{width:100%;border:1px solid #31556a;background:#071625;color:#eef8ff;padding:11px 12px;outline:none}
input:focus,select:focus{border-color:#68e0c3;box-shadow:0 0 0 2px #68e0c322}.actions{display:flex;justify-content:space-between;gap:12px;align-items:center}
input:invalid:not(:placeholder-shown){border-color:#d88b62}button{border:1px solid #376276;background:#10283a;color:#eaf7ff;padding:11px 18px;cursor:pointer}button.primary{background:#68e0c3;color:#03211b;border-color:#68e0c3;font-weight:700}
#status{min-height:20px;color:#f0ad78;font-size:12px}@media(max-width:620px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}}
</style></head><body><main>
<div class="heading"><img class="mark" src="__SETUP_ICON_DATA_URI__" alt="Open Sports Analyst logo"><div><span class="eyebrow">FIRST-RUN SETUP</span><h1>Open Sports Analyst</h1><p>Configure a model provider, or continue in deterministic mode and change this later.</p></div></div>
<form id="setup"><div class="grid">
<label><span class="field-name">Provider <span class="required" aria-hidden="true">*</span></span><select name="MODEL_PROVIDER" id="provider" required><option value="azure_foundry">Azure Foundry</option><option value="ollama">Ollama</option></select></label>
<p class="form-note"><span class="required" aria-hidden="true">*</span> Required field</p>
<div class="provider-fields azure" data-provider="azure_foundry">
<label><span class="field-name">Analysis model <span class="required" aria-hidden="true">*</span></span><input name="MODEL" placeholder="e.g. gpt-5.6-luna" required></label>
<label><span class="field-name">Reasoning effort <span class="optional">Optional</span></span><select name="REASONING_EFFORT"><option>medium</option><option>low</option><option>high</option><option>xhigh</option></select></label>
<label class="wide"><span class="field-name">Foundry endpoint <span class="required" aria-hidden="true">*</span></span><input name="FOUNDRY_ENDPOINT" type="url" placeholder="https://…openai.azure.com/openai/v1/" required><span class="hint">The endpoint for your Azure Foundry resource; it must end with /openai/v1/.</span></label>
<label class="wide field-key"><span class="field-name">Foundry API key <span class="required">Required unless already authenticated</span></span><input name="FOUNDRY_API_KEY" type="password" autocomplete="off" placeholder="Enter an API key or use your existing Azure sign-in"><span class="hint">Leave blank only if you have already authenticated to this specific Azure Foundry resource. If entered, the key is stored securely in Windows Credential Manager.</span></label>
</div>
<div class="provider-fields ollama" data-provider="ollama" hidden>
<label class="wide"><span class="field-name">Ollama URL <span class="required" aria-hidden="true">*</span></span><input name="OLLAMA_BASE_URL" type="url" value="http://127.0.0.1:11434" required><span class="hint">The address of the Ollama service running on this computer or your network.</span></label>
<label class="wide"><span class="field-name">Ollama model <span class="required" aria-hidden="true">*</span></span><input name="OLLAMA_MODEL" value="qwen3:8b" required><span class="hint">Use the exact name shown by Ollama, including its tag when applicable.</span></label>
</div>
<label class="wide"><span class="field-name">Chat model <span class="optional">Optional</span></span><input name="CHAT_MODEL" placeholder="Defaults to the provider's analysis model"><span class="hint">Only needed if summaries and follow-up responses should use a different model.</span></label>
</div><div id="status"></div><div class="actions"><button type="button" id="skip">Use deterministic mode</button><button class="primary" type="submit">Save and launch</button></div></form>
</main><script>
const form=document.querySelector('#setup'), provider=document.querySelector('#provider'), status=document.querySelector('#status');
function fields(){document.querySelectorAll('[data-provider]').forEach(group=>{const active=group.dataset.provider===provider.value;group.hidden=!active;group.querySelectorAll('input, select').forEach(control=>control.disabled=!active)})}
provider.addEventListener('change',fields);fields();
async function save(payload){status.textContent='Starting the local analysis service…';try{const result=await window.pywebview.api.save_configuration(payload);if(!result.ok)throw new Error(result.error);location.replace(result.url)}catch(error){status.textContent=String(error)}}
form.addEventListener('submit',event=>{event.preventDefault();save(Object.fromEntries(new FormData(form).entries()))});
document.querySelector('#skip').addEventListener('click',()=>save({MODEL_PROVIDER:'azure_foundry',MODEL:'',CHAT_MODEL:'',FOUNDRY_ENDPOINT:''}));
</script></body></html>
""".replace("__SETUP_ICON_DATA_URI__", SETUP_ICON_DATA_URI)


class DesktopController:
    def __init__(
        self,
        config_store: DesktopConfigStore | None = None,
        *,
        allow_configuration: bool = False,
        worker_context: Any | None = None,
    ) -> None:
        self.config_store = config_store or DesktopConfigStore()
        self.allow_configuration = allow_configuration or not self.config_store.setup_complete
        self.server: Any = None
        self.server_thread: threading.Thread | None = None
        self.socket: socket.socket | None = None
        self.worker_context = worker_context
        self.worker_process: Any = None
        self.worker_stop: Any = None
        self.url = ""

    def start_server(self) -> str:
        if self.url:
            return self.url

        import uvicorn

        from sports_analyst.api import create_app
        from sports_analyst.config import get_settings
        from sports_analyst.service import AnalystApplication

        # Desktop jobs always use the private AppData SQLite ledger. Ignore
        # cloud/self-hosting backend variables inherited from a developer shell.
        settings = get_settings().model_copy(update={"job_backend": "sqlite", "persistence_backend": "local"})

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = int(listener.getsockname()[1])
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(AnalystApplication(settings)),
                host="127.0.0.1",
                port=port,
                log_level="info",
                access_log=False,
                # A PyInstaller windowed executable has no stderr stream.
                # Uvicorn's default color formatter probes stderr.isatty()
                # during construction and otherwise prevents desktop startup.
                log_config=None,
            )
        )
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, name="sports-analyst-api", daemon=True)
        self.socket, self.server, self.server_thread = listener, server, thread
        self.url = f"http://127.0.0.1:{port}"
        thread.start()
        self._wait_until_ready()
        self._start_worker_if_configured(settings)
        return self.url

    def _start_worker_if_configured(self, settings: Any) -> None:
        if settings.job_backend != "sqlite" or (self.worker_process is not None and self.worker_process.is_alive()):
            return
        context = self.worker_context or multiprocessing.get_context("spawn")
        stop_event = context.Event()
        process = context.Process(
            target=_run_desktop_worker,
            args=(settings, stop_event),
            name="sports-analyst-worker",
            daemon=False,
        )
        process.start()
        self.worker_stop, self.worker_process = stop_event, process

    def save_configuration(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            if not self.allow_configuration:
                raise PermissionError("Configuration changes are not enabled for this session")
            self.config_store.save(payload)
            self.config_store.load_environment(overwrite=True)
            self.allow_configuration = False
            return {"ok": True, "url": self.start_server()}
        except Exception as error:
            return {"ok": False, "error": str(error)}

    def stop(self) -> None:
        if self.worker_stop is not None:
            self.worker_stop.set()
        if self.server is not None:
            self.server.should_exit = True
        if self.server_thread is not None and self.server_thread.is_alive():
            self.server_thread.join(timeout=5)
        if self.socket is not None:
            with suppress(OSError):
                self.socket.close()
        if self.worker_process is not None:
            self.worker_process.join(timeout=8)
            if self.worker_process.is_alive():
                self.worker_process.terminate()
                self.worker_process.join(timeout=3)
            with suppress(ValueError):
                self.worker_process.close()
        self.worker_process = self.worker_stop = None

    def _wait_until_ready(self, timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{self.url}/api/health", timeout=1) as response:
                    if response.status == 200:
                        return
            except Exception as error:
                last_error = error
                time.sleep(0.1)
        self.stop()
        raise RuntimeError(f"The local analysis service did not start: {last_error}")


APPLICATION_TITLE = "Open Sports Analyst"


def main(argv: list[str] | None = None) -> None:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="Launch Open Sports Analyst as a Windows desktop application.")
    parser.add_argument("--configure", action="store_true", help="Open first-run model configuration again.")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    config_store = DesktopConfigStore()
    config_store.load_environment()
    controller = DesktopController(config_store, allow_configuration=arguments.configure)
    if arguments.smoke_test:
        try:
            # These imports are deliberately exercised by the packaged smoke
            # test. The worker import is lazy in normal operation and could
            # otherwise disappear from a frozen desktop build.
            from sports_analyst.worker import run_worker  # noqa: F401

            controller.start_server()
            controller.stop()
        except Exception:
            if log_path := os.getenv("SPORTS_ANALYST_SMOKE_LOG"):
                import traceback

                Path(log_path).write_text(traceback.format_exc(), encoding="utf-8")
            raise
        return

    import webview

    initial_content: dict[str, str] = (
        {"url": controller.start_server()} if config_store.setup_complete and not arguments.configure else {"html": SETUP_HTML}
    )
    window = webview.create_window(
        APPLICATION_TITLE,
        js_api=controller,
        width=1440,
        height=900,
        min_size=(1024, 700),
        background_color="#06131f",
        **initial_content,
    )
    window.events.closed += controller.stop
    webview.start(debug=False)

if __name__ == "__main__":
    main()
