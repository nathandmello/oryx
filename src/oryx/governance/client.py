"""Verify the trusted customer endpoint before sending any request content."""
import os
from pathlib import Path
import socket
import stat

from .common import LIMIT, canonical, decode, identifier, shape
from .service import peer_uid

ENROLLMENT = Path("/etc/oryx/peer.json")


def enrollment(path=ENROLLMENT):
    path = Path(path).absolute()
    if path != path.resolve() or not path.is_file():
        raise PermissionError("Customer peer enrollment is unavailable")
    for node in (path, *path.parents):
        if node.stat().st_uid != 0 or node.stat().st_mode & 0o022:
            raise PermissionError("Customer peer enrollment requires a root-controlled trust anchor")
    cfg = shape(decode(path.read_bytes()), ("organization", "socket", "service_uid"))
    identifier(cfg["organization"])
    if type(cfg["service_uid"]) is not int or cfg["service_uid"] <= 0 or cfg["service_uid"] == os.geteuid():
        raise PermissionError("The customer service requires a distinct unprivileged identity")
    address = Path(cfg["socket"])
    if not address.is_absolute() or address.resolve() != address or not stat.S_ISSOCK(address.lstat().st_mode):
        raise PermissionError("Invalid customer peer socket")
    return cfg


def request(operation, payload, path=ENROLLMENT, *, expected_organization=None):
    cfg = enrollment(path)
    if expected_organization is not None and cfg["organization"] != expected_organization:
        raise PermissionError("Customer peer differs from the connected organization")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(20)
        sock.connect(cfg["socket"])
        if peer_uid(sock) != cfg["service_uid"]:
            raise PermissionError("Customer peer identity changed")
        packet = canonical({"organization":cfg["organization"], "operation":operation, "payload":payload})
        if len(packet) >= LIMIT:
            raise ValueError("Customer peer request too large")
        sock.sendall(packet+b"\n")
        with sock.makefile("rb") as stream:
            reply = decode(stream.readline(LIMIT+1))
    if reply.get("ok") is not True:
        raise ValueError(reply.get("error", "Unverified customer peer result"))
    return reply["result"]
