"""Child entry point for the storage supervisor, executed in a FRESH interpreter.

The supervisor used to ``fork()`` this module's child straight out of the running
ASGI server. Two things went wrong there, and both only appeared under real load:

1. A forked child of a multi-threaded process inherits only the calling thread while
   the parent's other threads keep running and holding their locks. The child could
   then block forever inside the SDK while the parent waited for a frame that never
   arrived, and the request failed as ``STORAGE_UNAVAILABLE`` (503) even though the
   bucket, the object and the credentials were all healthy.
2. The child closed every descriptor it could see in ``/proc/self/fd``. In a threaded
   parent that list is a moving target, so the child could close a descriptor another
   thread had just opened — including the parent's log file, which silently broke the
   server's own diagnostics.

``exec`` fixes both at the root. This module is run as a NEW interpreter, so the
child inherits no parent thread, no parent lock, and no parent descriptor at all.
The only thing handed across is the channel socket (one inheritable fd) and the
storage work description, which is plain JSON.

The work description is deliberately data-only: no callable, no closure, no SDK
client, no credential object. The child rebuilds its own client from the description
and the ambient credential environment the owner configured.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import sys
from contextlib import suppress

from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.storage_supervisor import (
    StorageChildChannel,
    run_storage_child,
)

#: Environment key carrying the channel socket descriptor number.
CHANNEL_FD_ENV = "KSI_STORAGE_CHILD_FD"
#: The FIXED descriptor number the parent copies the channel onto before the
#: child's interpreter starts. A descriptor's number is not preserved across
#: the exec boundary, so the child addresses the channel by this number.
CHANNEL_FD_NUMBER = 21
#: Environment key carrying the channel socket's inode. The child adopts the
#: socket with that inode — a descriptor's number is not preserved across the
#: exec boundary, but the file it points at is.
CHANNEL_INODE_ENV = "KSI_STORAGE_CHILD_INODE"
#: Environment key carrying the JSON work description.
WORK_ENV = "KSI_STORAGE_CHILD_WORK"


def _socket_descriptors() -> list[int]:
    found: list[int] = []
    try:
        for entry in os.listdir("/proc/self/fd"):
            try:
                found.append(int(entry))
            except ValueError:
                continue
    except OSError:
        pass
    return found


def _adopted_channel(fd: int) -> socket.socket | None:
    """Adopt the channel socket the parent passed into this process.

    The descriptor's NUMBER is not stable across the exec boundary, and the
    child may hold other sockets of its own, so the channel is found by
    IDENTITY: it is the ONE socket the parent passed, and the parent says
    which by the socket's inode. A descriptor that the parent opened has the
    same inode in the child; a socket the child created does not.

    ``socket.fromfd`` DUPLICATES the descriptor and keeps the socket type and
    its connection; ``socket.socket(fileno=...)`` would instead create a NEW
    socket object and attach the descriptor to it, dropping the connection.
    """
    # The descriptor's NUMBER is not preserved across the exec boundary, but
    # the file it points at is: the parent names the channel by its inode and
    # the child adopts exactly that socket.
    # The parent copies the channel onto a DEDICATED descriptor before the
    # child starts; that number is the child's address for it. The inode
    # confirms the descriptor is the same socket the parent handed over.
    wanted = os.environ.get(CHANNEL_INODE_ENV)
    for number in _socket_descriptors():
        try:
            if not stat.S_ISSOCK(os.fstat(number).st_mode):
                continue
            if wanted and str(os.fstat(number).st_ino) != wanted:
                continue
            return socket.fromfd(number, socket.AF_UNIX, socket.SOCK_STREAM)
        except OSError:
            continue
    return None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print("usage: storage_child [work-json]", file=sys.stderr)
        return 2
    raw_fd = os.environ.get(CHANNEL_FD_ENV)
    raw_work = args[0] if args else os.environ.get(WORK_ENV)
    if raw_fd is None or raw_work is None:
        print("storage child requires the channel fd and the work description", file=sys.stderr)
        return 2
    try:
        fd = int(raw_fd)
        work = json.loads(raw_work)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"storage child received an unusable description: {exc}", file=sys.stderr)
        return 2
    if not isinstance(work, dict):
        print("storage child work description must be an object", file=sys.stderr)
        return 2

    # The parent hands over the channel descriptor. Its NUMBER inside this
    # process is not guaranteed to be the number it had in the parent, so the
    # channel is found by looking for the socket the parent actually passed,
    # not by trusting a number.
    connection = _adopted_channel(fd)
    if connection is None:
        print("storage child could not adopt the channel descriptor", file=sys.stderr)
        return 2
    max_frame_bytes = int(work.get("maxFrameBytes") or 65536)
    channel = StorageChildChannel(connection, max_frame_bytes)
    try:
        run_storage_child(channel, work)
        channel.send_end()
    except SpatialDataDomainError as exc:
        # The refusal the child reports is the ANSWER; it is sent as a typed
        # frame, never as a traceback.
        with suppress(OSError):
            channel.send_failure(exc.reason, exc.status_code, exc.retryable)
    except BaseException:
        with suppress(OSError):
            channel.send_failure("STORAGE_UNAVAILABLE", 503, True)
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
