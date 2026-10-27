"""The sign-in's PKCE verifier survives the round trip through the state cookie,
and the exchange hands it back to the flow. No Google: the Flow is a stub."""

from docintel import auth


def test_the_state_cookie_carries_state_and_verifier_and_refuses_forgeries():
    raw = auth.pack_state("abc", "verifier-123")
    assert auth.unpack_state(raw) == ("abc", "verifier-123")
    assert auth.unpack_state(None) is None
    assert auth.unpack_state(raw[:-3] + "xyz") is None
    assert auth.unpack_state("abc") is None  # the old, unsigned shape


def test_the_exchange_passes_the_verifier_to_the_flow(monkeypatch):
    class _Flow:
        code_verifier = None
        credentials = "creds"
        seen = {}

        def fetch_token(self, code):
            _Flow.seen = {"code": code, "verifier": self.code_verifier}

        def authorization_url(self, **kw):
            self.code_verifier = "generated"
            return "https://accounts.google.com/x", "state-1"

    monkeypatch.setattr(auth, "_flow", lambda: _Flow())
    assert auth.authorization_url() == ("https://accounts.google.com/x", "state-1", "generated")
    assert auth.exchange_code("the-code", "generated") == "creds"
    assert _Flow.seen == {"code": "the-code", "verifier": "generated"}
