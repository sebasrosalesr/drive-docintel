from docintel.models import DriveFile
from docintel.sync import change_key, diff


def df(file_id, md5="", version="", modified="", status="done"):
    return DriveFile(watched_folder_id=1, file_id=file_id, md5=md5, version=version, modified_time=modified, status=status)


def test_diff_new_changed_unchanged_removed():
    local = {"a": df("a", md5="x"), "b": df("b", md5="y"), "c": df("c", md5="z"), "g": df("g", version="3", modified="t1")}
    remote = [{"id": "a", "md5Checksum": "x"}, {"id": "b", "md5Checksum": "y2"}, {"id": "d", "md5Checksum": "w"},
              {"id": "g", "mimeType": "application/vnd.google-apps.document", "version": "4", "modifiedTime": "t2"}]
    d = diff(remote, local)
    assert [f["id"] for f in d["new"]] == ["d"]
    assert sorted(f["id"] for f in d["changed"]) == ["b", "g"]
    assert [f["id"] for f in d["unchanged"]] == ["a"]
    assert [x.file_id for x in d["removed"]] == ["c"]


def test_google_native_files_use_version_and_modified_time():
    assert change_key({"version": "7", "modifiedTime": "2026-10-26T00:00:00Z"}) == "v7:2026-10-26T00:00:00Z"
    assert change_key({"md5Checksum": "abc", "version": "7"}) == "abc"


def test_removed_then_back_is_treated_as_changed():
    local = {"a": df("a", md5="x", status="removed")}
    d = diff([{"id": "a", "md5Checksum": "x"}], local)
    assert [f["id"] for f in d["changed"]] == ["a"] and not d["removed"]
