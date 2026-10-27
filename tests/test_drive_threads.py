"""The Drive client hands each thread its own authorized transport: httplib2 is
not thread-safe, and three downloads on one connection broke one and hung two."""

import threading

from docintel import drive


class _Creds:
    token = "t"
    expired = False
    valid = True

    def before_request(self, request, method, url, headers):
        headers["authorization"] = "Bearer t"


def test_each_thread_gets_its_own_transport_and_keeps_it(monkeypatch):
    monkeypatch.setattr(drive, "build", lambda *a, **kw: object())
    client = drive.GoogleDrive(_Creds())
    main_a, main_b = client._http(), client._http()
    assert main_a is main_b
    seen = {}

    def worker(name):
        seen[name] = client._http()

    threads = [threading.Thread(target=worker, args=(n,)) for n in ("x", "y")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen["x"] is not seen["y"] and seen["x"] is not main_a
    assert seen["x"].http.timeout == drive.HTTP_TIMEOUT
