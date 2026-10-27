import os
from pathlib import Path

from conftest import canned_response, extraction, metric
from sqlalchemy import select

from docintel import localfolder
from docintel.models import Document, LocalFile


def test_local_folder_pickup_change_and_removal(tmp_path, session, monkeypatch):
    monkeypatch.setattr(localfolder, "root", lambda: tmp_path)
    (tmp_path / "a.csv").write_text("month,fund,return\nJan 2026,Fund A,1.0\n")
    (tmp_path / ".hidden.csv").write_text("x")
    (tmp_path / "notes.json").write_text("{}")
    transport = lambda body: canned_response(extraction(metrics=[metric("Fund A", 1.0, ev="Jan 2026 | Fund A | 1.0")]))
    s1 = localfolder.tick(extract=False)
    assert (s1["listed"], s1["new"], s1["pending"]) == (2, 2, 1)   # json is listed but skipped, hidden ignored
    lf = session.scalar(select(LocalFile).where(LocalFile.name == "a.csv"))
    localfolder.process_local_file(lf.id, transport)
    session.refresh(lf)
    assert lf.status == "done" and lf.current_document_id
    # unchanged on the next tick
    assert localfolder.tick(extract=False)["unchanged"] == 2
    # edit the file: picked up as changed
    (tmp_path / "a.csv").write_text("month,fund,return\nJan 2026,Fund A,1.0\nFeb 2026,Fund A,2.0\n")
    os.utime(tmp_path / "a.csv", None)
    assert localfolder.tick(extract=False)["changed"] == 1
    # delete it: retired and its document hidden
    (tmp_path / "a.csv").unlink()
    assert localfolder.tick(extract=False)["removed"] == 1
    session.expire_all()
    assert session.get(LocalFile, lf.id).status == "removed"
    assert session.get(Document, lf.current_document_id).is_current is False
