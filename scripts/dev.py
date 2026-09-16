"""Start the one Python backend and its browser UI; Ctrl-C stops both."""
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service.local import operator_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-model", action="store_true", help="Allow paid Astra calls using the existing server-side key")
    parser.add_argument("--api-port", type=int, default=8010)
    parser.add_argument("--ui-port", type=int, default=5173)
    parser.add_argument("--node", default=shutil.which("node"))
    args = parser.parse_args()
    if not args.node:
        candidates = list((Path.home()/".cache/codex-runtimes").glob("*/dependencies/node/bin/node"))
        args.node = str(candidates[0]) if candidates else None
    if not args.node:
        parser.error("Node 22+ is required; supply --node /path/to/node")
    for port in (args.api_port, args.ui_port):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                parser.error(f"Local port {port} is occupied. Choose another --api-port or --ui-port.")
    env = {**os.environ, "CARTLY_BACKEND_URL": f"http://127.0.0.1:{args.api_port}", "CARTLY_SERVICE_KEY": operator_key()}
    # Operational readiness polling uses elapsed wall time; business dates
    # always come from data/config.json through the Python service.
    processes = []
    try:
        command = [sys.executable, "-m", "service", "serve", "--port", str(args.api_port)]
        if args.enable_model:
            command.append("--enable-model")
        api = subprocess.Popen(command, cwd=ROOT, env=env)
        processes.append(api)
        for _ in range(100):
            if api.poll() is not None:
                raise SystemExit("Python backend stopped. Check the port and startup output above.")
            try:
                with urllib.request.urlopen(env["CARTLY_BACKEND_URL"]+"/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(.2)
        else:
            raise SystemExit("Python backend did not become ready.")
        ui = subprocess.Popen([args.node, "scripts/run-framework.mjs", "dev", "--host", "127.0.0.1", "--port", str(args.ui_port), "--strictPort"], cwd=ROOT/"website", env=env)
        processes.append(ui)
        print(f"Cartly: http://127.0.0.1:{args.ui_port} — Python API: {env['CARTLY_BACKEND_URL']}", flush=True)
        print("Paid model calls " + ("enabled." if args.enable_model else "disabled. Add --enable-model for live chat."), flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
