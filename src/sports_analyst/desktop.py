# ruff: noqa: E501
from __future__ import annotations

import argparse
import socket
import threading
import time
import urllib.request
from contextlib import suppress
from typing import Any

from sports_analyst.desktop_config import DesktopConfigStore

SETUP_HTML = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Open Sports Analyst Setup</title><style>
:root{color-scheme:dark;font-family:Inter,Segoe UI,sans-serif;background:#06131f;color:#edf7ff}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:32px;background:radial-gradient(circle at 80% 0,#15394a 0,transparent 38%),#06131f}
main{width:min(760px,100%);border:1px solid #29495d;background:#0a1c2c;padding:34px;box-shadow:0 24px 80px #0008}
.eyebrow{color:#68e0c3;font:12px Consolas,monospace;letter-spacing:.14em}.heading{display:flex;gap:18px;align-items:center;margin-bottom:28px}.mark{width:58px;height:58px}
h1{font-size:29px;margin:5px 0 3px}p{color:#a7bfd0;line-height:1.5;margin:0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:15px;margin:26px 0}
label{display:grid;gap:6px;color:#bcd0dd;font-size:12px}.wide{grid-column:1/-1}input,select{width:100%;border:1px solid #31556a;background:#071625;color:#eef8ff;padding:11px 12px;outline:none}
input:focus,select:focus{border-color:#68e0c3;box-shadow:0 0 0 2px #68e0c322}.actions{display:flex;justify-content:space-between;gap:12px;align-items:center}
button{border:1px solid #376276;background:#10283a;color:#eaf7ff;padding:11px 18px;cursor:pointer}button.primary{background:#68e0c3;color:#03211b;border-color:#68e0c3;font-weight:700}
#status{min-height:20px;color:#f0ad78;font-size:12px}@media(max-width:620px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}}
</style></head><body><main>
<div class="heading"><img class="mark" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'%3E%3Ccircle cx='24' cy='24' r='22' fill='%23071320' stroke='%2368e0c3'/%3E%3Cpath d='M16 30v-9l8-5 8 5v9l-8 5z' fill='none' stroke='%2368e0c3' stroke-width='2'/%3E%3Cpath d='M24 16v19M16 21l16 9M32 21l-16 9' stroke='%2368e0c3'/%3E%3C/svg%3E"><div><span class="eyebrow">FIRST-RUN SETUP</span><h1>Open Sports Analyst</h1><p>Configure a model provider, or continue in deterministic mode and change this later.</p></div></div>
<form id="setup"><div class="grid">
<label>Provider<select name="MODEL_PROVIDER" id="provider"><option value="azure_foundry">Azure Foundry</option><option value="ollama">Ollama</option></select></label>
<label>Analysis model<input name="MODEL" placeholder="gpt-5.6-luna"></label>
<label>Chat model (optional)<input name="CHAT_MODEL" placeholder="Summary and follow-up wording"></label>
<label>Reasoning effort<select name="REASONING_EFFORT"><option>medium</option><option>low</option><option>high</option><option>xhigh</option></select></label>
<label class="wide azure">Foundry endpoint<input name="FOUNDRY_ENDPOINT" placeholder="https://…openai.azure.com/openai/v1/"></label>
<label class="wide azure">Foundry API key<input name="FOUNDRY_API_KEY" type="password" autocomplete="off" placeholder="Stored in Windows Credential Manager"></label>
<label class="wide ollama" hidden>Ollama URL<input name="OLLAMA_BASE_URL" value="http://127.0.0.1:11434"></label>
<label class="wide ollama" hidden>Ollama model<input name="OLLAMA_MODEL" value="qwen3:8b"></label>
</div><div id="status"></div><div class="actions"><button type="button" id="skip">Use deterministic mode</button><button class="primary" type="submit">Save and launch</button></div></form>
</main><script>
const form=document.querySelector('#setup'), provider=document.querySelector('#provider'), status=document.querySelector('#status');
function fields(){document.querySelectorAll('.azure').forEach(e=>e.hidden=provider.value!=='azure_foundry');document.querySelectorAll('.ollama').forEach(e=>e.hidden=provider.value!=='ollama')}
provider.addEventListener('change',fields);fields();
async function save(payload){status.textContent='Starting the local analysis service…';try{const result=await window.pywebview.api.save_configuration(payload);if(!result.ok)throw new Error(result.error);location.replace(result.url)}catch(error){status.textContent=String(error)}}
form.addEventListener('submit',event=>{event.preventDefault();save(Object.fromEntries(new FormData(form).entries()))});
document.querySelector('#skip').addEventListener('click',()=>save({MODEL_PROVIDER:'azure_foundry',MODEL:'',CHAT_MODEL:'',FOUNDRY_ENDPOINT:''}));
</script></body></html>
"""


class DesktopController:
    def __init__(self, config_store: DesktopConfigStore | None = None, *, allow_configuration: bool = False) -> None:
        self.config_store = config_store or DesktopConfigStore()
        self.allow_configuration = allow_configuration or not self.config_store.setup_complete
        self.server: Any = None
        self.server_thread: threading.Thread | None = None
        self.socket: socket.socket | None = None
        self.url = ""

    def start_server(self) -> str:
        if self.url:
            return self.url

        import uvicorn

        from sports_analyst.api import create_app

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = int(listener.getsockname()[1])
        server = uvicorn.Server(
            uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="info", access_log=False)
        )
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, name="sports-analyst-api", daemon=True)
        self.socket, self.server, self.server_thread = listener, server, thread
        self.url = f"http://127.0.0.1:{port}"
        thread.start()
        self._wait_until_ready()
        return self.url

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
        if self.server is not None:
            self.server.should_exit = True
        if self.server_thread is not None and self.server_thread.is_alive():
            self.server_thread.join(timeout=5)
        if self.socket is not None:
            with suppress(OSError):
                self.socket.close()

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
    parser = argparse.ArgumentParser(description="Launch Open Sports Analyst as a Windows desktop application.")
    parser.add_argument("--configure", action="store_true", help="Open first-run model configuration again.")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    config_store = DesktopConfigStore()
    config_store.load_environment()
    controller = DesktopController(config_store, allow_configuration=arguments.configure)
    if arguments.smoke_test:
        controller.start_server()
        controller.stop()
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
