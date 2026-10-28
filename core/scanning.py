"""Virus scanning for uploaded evidence. A file is only released for download once a scanner has
called it clean; with no scanner configured it stays "pending"."""

import logging
import socket
import struct
from importlib import import_module

from django.conf import settings

logger = logging.getLogger(__name__)

CHUNK = 64 * 1024


class Scanner:
    def scan(self, open_file) -> str:
        """Return 'clean', 'infected', 'failed' (could not scan) or 'pending' (no scanner)."""
        raise NotImplementedError


class UnconfiguredScanner(Scanner):
    def scan(self, open_file):
        return "pending"


class ClamdScanner(Scanner):
    """Talks to a ClamAV daemon using its INSTREAM command."""

    def __init__(self, host=None, port=None, timeout=30):
        self.host = host or settings.CLAMD_HOST
        self.port = port or settings.CLAMD_PORT
        self.timeout = timeout

    def scan(self, open_file):
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as connection:
                connection.sendall(b"zINSTREAM\0")
                with open_file() as stream:
                    while chunk := stream.read(CHUNK):
                        connection.sendall(struct.pack(">I", len(chunk)) + chunk)
                connection.sendall(struct.pack(">I", 0))
                reply = b""
                while not reply.endswith(b"\0") and (part := connection.recv(1024)):
                    reply += part
        except OSError:
            logger.exception("Virus scanner unreachable")
            return "failed"

        text = reply.rstrip(b"\0\n").decode(errors="replace")
        if text.endswith("OK"):
            return "clean"
        if text.endswith("FOUND"):
            return "infected"
        logger.error("Unexpected scanner reply: %s", text)
        return "failed"


def get_scanner() -> Scanner:
    module_path, class_name = settings.EVIDENCE_SCANNER.rsplit(".", 1)
    return getattr(import_module(module_path), class_name)()
