import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def wait_until():
    from PySide6.QtTest import QTest

    def wait(predicate, timeout=5000):
        deadline = time.monotonic() + timeout / 1000
        while not predicate():
            assert time.monotonic() < deadline, "Asynchronous preview did not become ready"
            QTest.qWait(10)

    return wait
