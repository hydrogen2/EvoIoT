"""Transport abstraction for collectors.

A transport is HOW the platform reaches a remote execution point to run a
request and get output back. It deliberately carries no knowledge of WHAT is
being fetched (that's the source's job) — it just executes.

Today: SSH-exec (run a command on a remote host that already sits on the target
network; the edge does raw protocol I/O, nothing more). The same interface is
meant to accept HTTP-exec / HTTPS-exec / vendor-API-exec transports later —
those differ only in how `exec` is fulfilled, not in the collector above them.

This is the edge/platform boundary: everything below exec() is the "dumb edge"
(execute and return bytes); everything above is the "smart platform"
(what to run, when, how to interpret).
"""

import os
import subprocess
from abc import ABC, abstractmethod


class Transport(ABC):
    @abstractmethod
    def exec(self, request: str, timeout: int = 90) -> str:
        """Run a request at the remote execution point, return raw stdout.
        For SSH the request is a shell command; other transports may define
        their own request encoding while keeping this same contract."""
        ...


class SshTransport(Transport):
    """Execute a command on a remote host over SSH. The host is expected to be
    on the target's network (e.g. a BMS-LAN gateway), so protocol I/O runs
    natively there and only the request/result cross SSH."""

    def __init__(self, target: str, key: str = None,
                 options: list = None):
        self.target = target
        self.key = key or os.environ.get("COLLECTOR_SSH_KEY", "/root/.ssh/id_ed25519")
        # tailscale already authenticates+encrypts the path, so host-key
        # management adds little; accept-new keeps it simple.
        self.options = options or [
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "UserKnownHostsFile=/root/.ssh/known_hosts",
            "-o", "ConnectTimeout=10",
        ]

    def exec(self, request: str, timeout: int = 90) -> str:
        cmd = ["ssh", "-i", self.key, *self.options, self.target, request]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(f"ssh exec failed ({r.returncode}): {r.stderr.strip()[:400]}")
        return r.stdout


def build_transport(spec: dict) -> Transport:
    """Instantiate a transport from a data_sources.config['transport'] block."""
    ttype = (spec or {}).get("type", "ssh")
    if ttype == "ssh":
        return SshTransport(target=spec["target"], key=spec.get("key"))
    # Future: "http", "https", "api" — same Transport contract.
    raise ValueError(f"unknown transport type: {ttype}")
