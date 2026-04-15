from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
import threading
import time

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Perch backend launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--max-port", type=int, default=8100)
    return parser.parse_args()


def _find_available_port(host: str, preferred_port: int, max_port: int) -> int:
    for port in range(preferred_port, max_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port available in range {preferred_port}-{max_port}")


def _emit_event(event_type: str, payload: dict) -> None:
    message = {"type": event_type, **payload}
    print(f"PERCH_EVENT {json.dumps(message, ensure_ascii=True)}", flush=True)


def _run_event_stream(stop_event: threading.Event, host: str, port: int, server: uvicorn.Server) -> None:
    from app.main import get_monitoring_state, get_pet_update_payload

    while not stop_event.is_set() and not server.started:
        time.sleep(0.05)

    if stop_event.is_set():
        return

    _emit_event("ready", {"host": host, "port": port})

    while not stop_event.is_set() and not server.should_exit:
        try:
            pet = get_pet_update_payload().model_dump()
            _emit_event("pet:update", {"data": pet})
            monitoring_state = get_monitoring_state().model_dump(mode="json")
            _emit_event("monitoring:state", {"data": monitoring_state})
        except Exception as exc:  # pragma: no cover - best effort stream
            _emit_event("bridge:error", {"message": str(exc)})
        stop_event.wait(1.0)


def main() -> None:
    args = _parse_args()
    port = _find_available_port(host=args.host, preferred_port=args.port, max_port=args.max_port)

    config = uvicorn.Config("app.main:app", host=args.host, port=port, log_level="info")
    server = uvicorn.Server(config)

    stop_event = threading.Event()
    event_thread = threading.Thread(
        target=_run_event_stream,
        args=(stop_event, args.host, port, server),
        daemon=True,
    )
    event_thread.start()

    try:
        server.run()
    finally:
        stop_event.set()
        event_thread.join(timeout=1.5)


if __name__ == "__main__":
    main()
