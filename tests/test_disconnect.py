"""Disconnect Drive: the account, its folders and file rows go, the session
ends, and the documents already read stay, untied from any Drive file."""

from conftest import canned_response, extraction, metric
from fastapi.testclient import TestClient
from sqlalchemy import select

from docintel import auth
from docintel.main import app
from docintel.models import Document, DriveFile, GoogleAccount, User, WatchedFolder
from docintel.pipeline import process_bytes

client = TestClient(app)


def test_disconnect_forgets_the_account_and_keeps_the_library(session):
    user = User(email="sebas@example.com", name="Sebastian"); session.add(user); session.flush()
    acct = GoogleAccount(user_id=user.id, google_sub="sub-1", email=user.email, refresh_token_enc="enc"); session.add(acct); session.flush()
    folder = WatchedFolder(google_account_id=acct.id, folder_id="f1", folder_name="Demo"); session.add(folder); session.flush()
    df = DriveFile(watched_folder_id=folder.id, file_id="x1", name="a.txt", mime="text/plain", status="done"); session.add(df); session.commit()
    doc = process_bytes(session, name="a.txt", mime="text/plain", data=b"Jan 2026 1.0", drive_file=df, source="drive",
                        transport=lambda b: canned_response(extraction(metrics=[metric("Alpha Fund", 1.0, ev="Jan 2026 1.0")])), force=True)
    assert doc.drive_file_id == df.id

    assert client.post("/api/auth/google/disconnect").status_code == 401  # nobody signed in
    client.cookies.set(auth.SESSION_COOKIE, auth._signer.dumps({"uid": user.id}))
    r = client.post("/api/auth/google/disconnect")
    assert r.status_code == 200 and r.json() == {"ok": True, "folders": 1}
    assert "docintel_session=" in r.headers.get("set-cookie", "") and "Max-Age=0" in r.headers.get("set-cookie", "")

    user_id, doc_id = user.id, doc.id
    session.expunge_all()  # drop the identity map: the rows are gone, the instances must not answer for them
    assert session.scalar(select(GoogleAccount)) is None and session.scalar(select(WatchedFolder)) is None and session.scalar(select(DriveFile)) is None
    assert session.get(User, user_id) is None
    kept = session.get(Document, doc_id)
    assert kept is not None and kept.drive_file_id is None
