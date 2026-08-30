########################################################################
### SANDBOX -- run one PyMuPDF op in a locked-down child process.
### A hostile PDF that trips a MuPDF memory bug, blows up allocation, or
### loops forever kills one short-lived worker, not the request process.
### POSIX non-frozen only; elsewhere run() calls the function directly.
### PDFXML_SANDBOX=0 disables it anywhere.
########################################################################
import multiprocessing
import os
import sys
import time

from app import pdfops
from app.extensions import (
    SANDBOX_CPU_SECONDS, SANDBOX_MEMORY_MB, SANDBOX_TIMEOUT_SECONDS, logger,
)

ENABLED = (
    os.name == "posix"
    and not getattr(sys, "frozen", False)
    and os.environ.get("PDFXML_SANDBOX", "1") != "0"
)

### forkserver, not spawn (fitz preloaded, so a call costs a fork) and
### not fork() (the request process is threaded).
if ENABLED:
    _ctx = multiprocessing.get_context("forkserver")
    _ctx.set_forkserver_preload(["fitz"])
else:
    _ctx = None


class SandboxError(RuntimeError):
    pass


class SandboxTimeout(SandboxError):
    pass


def run(func, *args):
    """Run pdfops.<func>(*args) in the sandbox. Any failure -- in-worker
    or direct-call -- surfaces as SandboxError."""
    if not ENABLED:
        try:
            return func(*args)
        except Exception as exc:
            raise SandboxError(f"{type(exc).__name__}: {exc}") from exc

    rlimit_as = SANDBOX_MEMORY_MB * 1024 * 1024 if SANDBOX_MEMORY_MB else 0
    rlimit_cpu = SANDBOX_CPU_SECONDS or 0

    recv_conn, send_conn = _ctx.Pipe(duplex=False)
    proc = _ctx.Process(
        target=pdfops.worker_entry,
        args=(send_conn, rlimit_as, rlimit_cpu, func, args),
        daemon=True,
    )
    proc.start()
    send_conn.close()  # parent keeps only the read end

    try:
        ### poll in slices + watch is_alive() -- a signal-killed worker
        ### may not close the pipe fast enough to unblock a lone poll().
        deadline = time.monotonic() + SANDBOX_TIMEOUT_SECONDS
        while True:
            if recv_conn.poll(0.1):
                break
            if not proc.is_alive():
                proc.join()
                logger.warning("sandbox: %s worker died (code %s)", func.__name__, proc.exitcode)
                raise SandboxError(f"PDF worker exited abnormally (code {proc.exitcode})")
            if time.monotonic() >= deadline:
                proc.kill()
                logger.warning("sandbox: killed %s after %ss", func.__name__, SANDBOX_TIMEOUT_SECONDS)
                raise SandboxTimeout(f"PDF operation timed out after {SANDBOX_TIMEOUT_SECONDS}s")
        try:
            ok, payload = recv_conn.recv()
        except EOFError:
            proc.join()
            logger.warning("sandbox: %s worker died (code %s)", func.__name__, proc.exitcode)
            raise SandboxError(f"PDF worker exited abnormally (code {proc.exitcode})")
        if not ok:
            logger.warning("sandbox: %s failed -- %s", func.__name__, payload)
            raise SandboxError(payload)
        return payload
    finally:
        recv_conn.close()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join()
