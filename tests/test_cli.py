import argparse
from datetime import datetime, time

import pytest

from conftest import requires_engine
from flexsched.cli import main, parse_block, parse_clock, parse_datetime, table


def test_parse_datetime_accepts_common_formats():
    assert parse_datetime("2026-10-07 13:30") == datetime(2026, 10, 7, 13, 30)
    assert parse_datetime("2026-10-07T13:30") == datetime(2026, 10, 7, 13, 30)
    assert parse_datetime("2026-10-07") == datetime(2026, 10, 7)
    with pytest.raises(argparse.ArgumentTypeError):
        parse_datetime("next tuesday")


def test_parse_block_and_clock():
    assert parse_block("2026-10-07 13:00-14:00") == (datetime(2026, 10, 7, 13),
                                                     datetime(2026, 10, 7, 14))
    assert parse_clock("08:45") == time(8, 45)
    with pytest.raises(argparse.ArgumentTypeError):
        parse_block("2026-10-07 14:00-13:00")


def test_table_aligns_columns():
    out = table(["a", "long header"], [[1, "x"], [22, "yy"]]).splitlines()
    assert len({len(line.rstrip()) for line in out[:2]}) == 1  # header and rule align
    assert out[1].startswith("--")


def test_add_list_and_validation(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    assert main(["--db", db, "add", "Write report", "-c", "writing", "-d", "3",
                 "-p", "4", "-e", "45", "--deadline", "2030-01-08 17:00"]) == 0
    assert main(["--db", db, "list"]) == 0
    out = capsys.readouterr().out
    assert "Write report" in out and "2030-01-08 17:00" in out
    with pytest.raises(SystemExit):  # argparse rejects difficulty 9
        main(["--db", db, "add", "x", "-c", "coding", "-d", "9", "-e", "10"])


def test_train_without_data_fails_gracefully(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "t.db"), "train"]) == 1
    assert "need at least" in capsys.readouterr().err


@requires_engine
def test_full_cli_workflow(tmp_path, capsys):
    common = ["--db", str(tmp_path / "t.db"), "--model", str(tmp_path / "m.joblib")]
    assert main(common + ["seed", "--days", "60"]) == 0
    assert main(common + ["train"]) == 0
    assert main(common + ["stats"]) == 0
    assert main(common + ["add", "Big feature", "-c", "coding", "-d", "5", "-p", "5",
                          "-e", "90"]) == 0
    assert main(common + ["plan", "--start", "2030-01-07", "--days", "1",
                          "--block", "2030-01-07 13:00-14:00"]) == 0
    assert main(common + ["runs"]) == 0
    out = capsys.readouterr().out
    assert "chosen" in out and "Big feature" in out and "fatigue_aware" in out
