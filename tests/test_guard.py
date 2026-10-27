import pytest

from docintel.ask import guard


@pytest.mark.parametrize("sql", [
    "select * from documents", "SELECT 1; DROP TABLE funds", "PRAGMA table_info(funds)", "ATTACH DATABASE '/tmp/x' AS y",
    "INSERT INTO funds(name) VALUES('x')", "SELECT * FROM sqlite_master", "UPDATE funds SET name='x'", "DELETE FROM observations",
    "WITH w AS (INSERT INTO funds(name) VALUES('x') RETURNING id) SELECT * FROM w", "SELECT load_extension('x')", "",
])
def test_rejected_statements(sql):
    with pytest.raises(guard.SQLRejected):
        guard.check(sql)


def test_allowed_and_limited():
    s = guard.check("SELECT fund, value FROM v_observations WHERE metric='return' -- best")
    assert s.endswith("LIMIT 200") and "--" not in s
    assert guard.check("SELECT * FROM v_observations LIMIT 5").endswith("LIMIT 5")
    assert guard.check("WITH t AS (SELECT * FROM v_observations) SELECT count(*) FROM t").startswith("WITH")


def test_run_against_empty_views_and_authorizer_blocks_raw_text(session):
    cols, rows = guard.run("SELECT count(*) AS n FROM v_observations")
    assert cols == ["n"] and rows[0][0] >= 0
    with pytest.raises(Exception):
        guard._run_sqlite("SELECT raw_text FROM documents LIMIT 1")
    with pytest.raises(Exception):
        guard._run_sqlite("SELECT * FROM google_accounts")
