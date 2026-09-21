#!/usr/bin/env python3
"""
scripts/throughput_server.py
Controlled Local HTTP Throughput Benchmark Server.

Provides a lightweight, zero-dependency, deterministic HTTP payload server
for verifying application-layer network throughput without relying on
uncontrolled external internet servers.
"""

from __future__ import annotations

import argparse
import http.server
import json
import socketserver
import sys
import threading
from urllib.parse import urlparse, parse_qs


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8088
DEFAULT_PAYLOAD_SIZE = 1048576  # 1 MB (1,048,576 bytes)
CHUNK_SIZE = 65536              # 64 KB streaming chunk
DETERMINISTIC_CHUNK = b"WIFI_MAPPER_THROUGHPUT_PAYLOAD_BLOCK_" * 1776  # exactly 65536 bytes


class ThroughputHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler providing deterministic payload generation."""

    def log_message(self, format: str, *args) -> None:
        """Override to suppress request logging unless debugging."""
        if getattr(self.server, "verbose", False):
            super().log_message(format, *args)

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path in ("/health", "/status"):
            self._handle_health()
        elif path in ("/payload", "/data", "/"):
            self._handle_payload(parsed_url)
        else:
            self.send_error(404, f"Endpoint {path} not found. Use /payload or /health")

    def _handle_health(self) -> None:
        """Return simple JSON health status."""
        body = json.dumps({
            "status": "ok",
            "service": "throughput_server",
            "default_payload_bytes": getattr(self.server, "default_payload_size", DEFAULT_PAYLOAD_SIZE),
        }).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _handle_payload(self, parsed_url) -> None:
        """Stream deterministic binary payload of requested size in bytes."""
        query_params = parse_qs(parsed_url.query)
        requested_size = getattr(self.server, "default_payload_size", DEFAULT_PAYLOAD_SIZE)

        if "size" in query_params:
            try:
                requested_size = max(1, int(query_params["size"][0]))
            except ValueError:
                self.send_error(400, "Invalid size parameter: must be an integer")
                return

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(requested_size))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("X-Payload-Bytes", str(requested_size))
        self.end_headers()

        # Stream payload in chunks to avoid large memory allocations
        bytes_remaining = requested_size
        chunk_len = len(DETERMINISTIC_CHUNK)

        try:
            while bytes_remaining > 0:
                to_send = min(bytes_remaining, chunk_len)
                if to_send == chunk_len:
                    self.wfile.write(DETERMINISTIC_CHUNK)
                else:
                    self.wfile.write(DETERMINISTIC_CHUNK[:to_send])
                bytes_remaining -= to_send
        except (ConnectionResetError, BrokenPipeError):
            # Client disconnected early (e.g. timeout)
            pass


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Multi-threaded HTTP server allowing concurrent throughput requests."""
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass, default_payload_size=DEFAULT_PAYLOAD_SIZE, verbose=False):
        super().__init__(server_address, RequestHandlerClass)
        self.default_payload_size = default_payload_size
        self.verbose = verbose


def start_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    default_payload_size: int = DEFAULT_PAYLOAD_SIZE,
    verbose: bool = False,
) -> ThreadedHTTPServer:
    """Create and return an active ThreadedHTTPServer instance."""
    server = ThreadedHTTPServer(
        (host, port),
        ThroughputHTTPRequestHandler,
        default_payload_size=default_payload_size,
        verbose=verbose,
    )
    return server


def run_in_thread(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    default_payload_size: int = DEFAULT_PAYLOAD_SIZE,
) -> tuple[ThreadedHTTPServer, threading.Thread]:
    """Helper to run the server in a daemon background thread (ideal for automated tests)."""
    server = start_server(host=host, port=port, default_payload_size=default_payload_size)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Controlled Local HTTP Throughput Benchmark Server"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help=f"Host address to bind (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=DEFAULT_PAYLOAD_SIZE,
        help=f"Default payload size in bytes (default: {DEFAULT_PAYLOAD_SIZE} bytes = 1MB)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose request logging",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("  Wi-Fi Performance Mapper - Controlled Throughput Server")
    print("=" * 60)
    print(f"  Listening on:     http://{args.host}:{args.port}")
    print(f"  Health endpoint:  http://{args.host}:{args.port}/health")
    print(f"  Payload endpoint: http://{args.host}:{args.port}/payload")
    print(f"  Custom size url:  http://{args.host}:{args.port}/payload?size=<bytes>")
    print(f"  Default payload:  {args.size:,} bytes ({args.size / (1024*1024):.2f} MB)")
    print("=" * 60)
    print("  Press Ctrl+C to stop server.\n")

    try:
        server = start_server(
            host=args.host,
            port=args.port,
            default_payload_size=args.size,
            verbose=args.verbose,
        )
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping throughput server...")
    finally:
        server.server_close()
        print("Server shutdown complete.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
