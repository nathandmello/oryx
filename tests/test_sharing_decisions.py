"""A proposal decision accepts input on the foreground PM's non-seekable terminal."""
from contextlib import redirect_stdout
import io
import json
import os
import pty
import select
import termios
import unittest
from unittest.mock import patch

import test_pm  # Sets up the same source import paths used by the other command tests.
from oryx.review import cli as review
from oryx.sharing import cli as sharing


class SharingDecisionTests(unittest.TestCase):
    def exercise(self, operation, supplied, expected, approve=None):
        body = {"proposal": "p", "candidate": "reviewed-version"}
        if approve is not None:
            body["approve"] = approve
        shown = {"candidate": body["candidate"], "content": "Exact wording to review"}
        stdout = io.StringIO()
        master, slave = pty.openpty()
        try:
            attrs = termios.tcgetattr(slave)
            attrs[3] &= ~termios.ECHO
            termios.tcsetattr(slave, termios.TCSANOW, attrs)
            os.write(master, supplied)
            with patch.object(review.os, "open", side_effect=lambda *args: os.dup(slave)), \
                 patch.object(review.os, "tcgetpgrp", return_value=os.getpgrp()), \
                 patch.object(sharing, "read_body", return_value=body), \
                 patch.object(sharing, "request", side_effect=[shown, {"status": "recorded"}]) as peer, \
                 redirect_stdout(stdout):
                self.assertEqual(sharing.main([operation]), 0)
            self.assertEqual(json.loads(stdout.getvalue())["status"], expected)
            transcript = b""
            while select.select([master], [], [], 0)[0]:
                transcript += os.read(master, 4096)
            self.assertIn(shown["content"].encode(), transcript)
            if expected == "recorded":
                self.assertEqual(peer.call_args.args, (operation, body))
            else:
                peer.assert_called_once_with("inspect", {"proposal": "p"})
        finally:
            os.close(master)
            os.close(slave)

    def test_only_the_named_foreground_decision_reaches_the_peer(self):
        self.exercise("review", b"APPROVE\n", "recorded", True)
        self.exercise("review", b"DECLINE\n", "recorded", False)
        self.exercise("merge", b"MERGE\n", "recorded")
        self.exercise("merge", b"APPROVE\n", "no-decision")
