
import sys
from datetime import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import clean_route_data as c


def make_row(**overrides):
    row = {"PublicRouteID": "Route-00001", "PublicDriverName": "Driver 001",
           "RouteDateRaw": 80326, "DayOfWeek": "Monday", "Status": "Completed",
           "CheckedIn": 1, "MorningCheckIn": False, "ArrivalTimeOnly": time(17, 30)}
    row.update(overrides)
    return row


def run(*rows):
    return c.clean(pd.DataFrame(rows), c.Report())


def test_leading_zero_restored_in_date():
    out = run(make_row())
    assert out.loc[0, "RouteDate"] == "2026-08-03"


def test_midnight_placeholder_becomes_blank():
    out = run(make_row(Status="No Show", CheckedIn=0, ArrivalTimeOnly=time(0, 0)))
    assert pd.isna(out.loc[0, "ArrivalHour"])


def test_arrival_hour_is_decimal():
    out = run(make_row())
    assert out.loc[0, "ArrivalHour"] == 17.5


def test_morning_checkin_text_and_fraction_and_junk():
    out = run(make_row(PublicRouteID="Route-00001", MorningCheckIn="6:05pm"),
              make_row(PublicRouteID="Route-00002", MorningCheckIn=0.75),
              make_row(PublicRouteID="Route-00003", MorningCheckIn="any minute now"))
    assert out.loc[0, "MorningCheckInTime"] == "18:05:00"
    assert out.loc[1, "MorningCheckInTime"] == "18:00:00"
    assert pd.isna(out.loc[2, "MorningCheckInFlag"])
    assert "Unreadable MorningCheckIn" in out.loc[2, "DataQualityNotes"]


def test_empty_rows_are_dropped():
    blank = {k: None for k in make_row()}
    out = run(make_row(), blank, blank)
    assert len(out) == 1


def test_missing_route_id_is_flagged_not_invented():
    out = run(make_row(PublicRouteID=None))
    assert pd.isna(out.loc[0, "RouteID"])
    assert "Missing RouteID" in out.loc[0, "DataQualityNotes"]


def test_status_conflict_is_flagged():
    out = run(make_row(Status="Completed", CheckedIn=0))
    assert "CheckedIn contradicts Status" in out.loc[0, "DataQualityNotes"]


def test_exact_duplicate_removed():
    out = run(make_row(), make_row())
    assert len(out) == 1
