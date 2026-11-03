
#Tarun's Route cleaning program
#I made this to run and append to a sqlite database as an example and due to privacy reasons.


# IMPORTS

import argparse
import sqlite3                       
from datetime import datetime, time
from pathlib import Path        

import numpy as np                   
import pandas as pd                  

# CONFIG

COLUMNS = {
    "route_id":   "PublicRouteID",
    "driver":     "PublicDriverName",
    "date":       "RouteDateRaw",
    "weekday":    "DayOfWeek",
    "status":     "Status",
    "checked_in": "CheckedIn",
    "morning":    "MorningCheckIn",
    "arrival":    "ArrivalTimeOnly",
}

REQUIRED_COLUMNS = ["date", "driver", "status"]
MIN_FILLED = 2

DATE_FORMAT = "%m%d%y"                      
ROUTE_ID_PATTERN = r"^Route-\d{5}$"         
MIDNIGHT = time(0, 0, 0)                    # placeholder for null values

#status values that matter
VALID_STATUSES = {"Completed": 1, "No Show": 0, "MorningCheckIn": 0}

STATUS_ALIASES = {
    "completed": "Completed",
    "no show": "No Show", "noshow": "No Show", "no-show": "No Show",
    "morningcheckin": "MorningCheckIn", "morning check in": "MorningCheckIn",
    "morning check-in": "MorningCheckIn",
}

#accounting for bad tracking in src file.
SUSPICIOUS_NOSHOW_RATE = 0.50
MIN_ROUTES_FOR_RATE = 10

NOTES_COL = "DataQualityNotes"


class Report:

    def __init__(self):
        self.lines = []

    def log(self, message):
        self.lines.append(message)
        print(message)

    def save(self, path):
        Path(path).write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def add_note(df, mask, message):            #returns flagged rows for review. Does not allow for null values to count as 0

    mask = mask.fillna(False).astype(bool)
    existing = df.loc[mask, NOTES_COL]
    df.loc[mask, NOTES_COL] = existing.where(existing == "", existing + "; ") + message
    return int(mask.sum())


def parse_time_value(value):        #sorts through different time record types/errors made during input

    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if value is pd.NaT:
        return None

    
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    if isinstance(value, time):
        return value.replace(microsecond=0)

 
    if isinstance(value, bool):
        return None

    #converts excel time values between 0 and 1 into actual time without rounding.
    if isinstance(value, (int, float)):
        if 0 <= value < 1:
            total_seconds = int(round(value * 86400))        
            total_seconds = min(total_seconds, 86399)        
            return time(total_seconds // 3600, (total_seconds % 3600) // 60, total_seconds % 60)
        return None

    
    text = str(value).strip().lower().replace(" ", "") 
    for fmt in ("%I:%M%p", "%I%p", "%H:%M:%S", "%H:%M", "%H:%M:%S.%f"):
        try:
            return datetime.strptime(text, fmt).time().replace(microsecond=0)
        except ValueError:
            continue
    return None


#file reading
def step_1_load(path, sheet, report):

    path = Path(path)
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    if path.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        df = pd.read_excel(path, sheet_name=sheet)
    elif path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        raise SystemExit("Unsupported file type. Use .xlsx or .csv")

    report.log(f"[1] Loaded '{path.name}': {len(df):,} rows, {len(df.columns)} columns")

 
    missing = [c for c in COLUMNS.values() if c not in df.columns]
    if missing:
        raise SystemExit(f"Missing expected columns: {missing}\nFound: {list(df.columns)}")
    return df


#delete null rows/values
def step_2_drop_empty_rows(df, report):

    required = [COLUMNS[k] for k in REQUIRED_COLUMNS]
    filled_per_row = df[required].notna().sum(axis=1)   # how many required cells each row has
    has_data = filled_per_row >= MIN_FILLED
    removed = int((~has_data).sum())
    df = df[has_data].copy()
    report.log(f"[2] Removed {removed:,} empty/phantom rows -> {len(df):,} real rows remain")
    return df.reset_index(drop=True)


#clean and rename
def step_3_clean_text(df, report):

    df = df.rename(columns={
        COLUMNS["route_id"]: "RouteID",
        COLUMNS["driver"]: "DriverName",
        COLUMNS["weekday"]: "DayOfWeek",
        COLUMNS["status"]: "Status",
        COLUMNS["checked_in"]: "CheckedIn",
        COLUMNS["morning"]: "MorningCheckIn",
        COLUMNS["arrival"]: "ArrivalTimeOnly",
        COLUMNS["date"]: "RouteDateRaw",
    })

    for col in ["RouteID", "DriverName", "DayOfWeek", "Status"]:
        df[col] = df[col].astype("string").str.strip()   

    df["DayOfWeek"] = df["DayOfWeek"].str.title()       

    
    lookup = df["Status"].str.lower().map(STATUS_ALIASES)
    fixed = lookup.notna() & (lookup != df["Status"])
    df.loc[fixed, "Status"] = lookup[fixed]
    report.log(f"[3] Trimmed text columns; standardized {int(fixed.sum())} status spellings")

    df[NOTES_COL] = ""

    #Flagging>deleting
    bad = ~df["Status"].isin(VALID_STATUSES.keys())
    n = add_note(df, bad, "Unknown status")
    if n:
        report.log(f"    ! {n} rows have a status that is not one of {list(VALID_STATUSES)}")
    return df


#date cleaning
def step_4_fix_dates(df, report):
  
    before = (
        df["RouteDateRaw"].astype("string").str.strip()
        .str.replace(r"\.0$", "", regex=True)           
    )
    as_text = before.str.zfill(6)                        
    padded = int((before.str.len() < 6).sum())           
    df["RouteDate"] = pd.to_datetime(as_text, format=DATE_FORMAT, errors="coerce")

    bad_dates = add_note(df, df["RouteDate"].isna(), "Unreadable date")
    report.log(f"[4] Parsed dates (restored the leading zero on {padded:,} values); "
               f"{bad_dates} unreadable")

   #verify weekday with date for increesed accuracy.
    mismatch = df["RouteDate"].notna() & (df["RouteDate"].dt.day_name() != df["DayOfWeek"])
    n = add_note(df, mismatch, "Weekday does not match date")
    report.log(f"    Weekday vs date mismatches flagged: {n}")

    df["RouteDate"] = df["RouteDate"].dt.strftime("%Y-%m-%d") 
    return df.drop(columns=["RouteDateRaw"])


#Time values; remove 0,0,0 values
def step_5_fix_arrival(df, report):
 
    parsed = df["ArrivalTimeOnly"].map(parse_time_value)

    placeholder = parsed.map(lambda t: t == MIDNIGHT)
    parsed = parsed.where(~placeholder, None)         

    df["ArrivalTime"] = parsed.map(lambda t: t.strftime("%H:%M:%S") if t else None)
    df["ArrivalHour"] = parsed.map(lambda t: round(t.hour + t.minute / 60 + t.second / 3600, 2) if t else None)
    df["ArrivalHour"] = pd.to_numeric(df["ArrivalHour"])

    report.log(f"[5] Converted arrival times; replaced {int(placeholder.sum()):,} midnight placeholders with blanks")

    #flag null values
    n = add_note(df, (df["Status"] == "Completed") & df["ArrivalTime"].isna(),
                 "Completed route has no arrival time")
    report.log(f"    Completed routes missing an arrival time (flagged): {n}")
    return df.drop(columns=["ArrivalTimeOnly"])


#Morning Check In
def step_6_fix_morning_checkin(df, report):

    flags, times, unreadable = [], [], []

    for value in df["MorningCheckIn"]:
        if isinstance(value, (bool, np.bool_)) or str(value).strip().lower() in ("true", "false"):
            flags.append(1 if str(value).strip().lower() == "true" else 0)
            times.append(None)
            unreadable.append(False)
            continue

        if value is None or (isinstance(value, float) and pd.isna(value)):
            flags.append(None); times.append(None); unreadable.append(False)
            continue

        parsed = parse_time_value(value)
        if parsed is not None:
            flags.append(1); times.append(parsed.strftime("%H:%M:%S")); unreadable.append(False)
        else:

            flags.append(None); times.append(None); unreadable.append(True)

    df["MorningCheckInFlag"] = pd.array(flags, dtype="Int64")     
    df["MorningCheckInTime"] = times
    n = add_note(df, pd.Series(unreadable, index=df.index), "Unreadable MorningCheckIn value")

    report.log(f"[6] Split MorningCheckIn into Flag + Time columns; "
               f"{int(df['MorningCheckInFlag'].eq(1).sum()):,} yes, "
               f"{int(df['MorningCheckInFlag'].eq(0).sum()):,} no, "
               f"{int(df['MorningCheckInFlag'].isna().sum()):,} unknown ({n} unreadable)")
    return df.drop(columns=["MorningCheckIn"])


#logic check between status and checked in column

def step_7_check_consistency(df, report):

    df["CheckedIn"] = pd.to_numeric(df["CheckedIn"], errors="coerce").astype("Int64")

    expected = df["Status"].map(VALID_STATUSES).astype("Int64")
    conflict = df["CheckedIn"].notna() & expected.notna() & (df["CheckedIn"] != expected)
    n1 = add_note(df, conflict, "CheckedIn contradicts Status")

    morning_conflict = (df["Status"] == "MorningCheckIn") & (df["MorningCheckInFlag"] != 1)
    n2 = add_note(df, morning_conflict, "Status is MorningCheckIn but morning flag is not 1")

    report.log(f"[7] Consistency checks: {n1} CheckedIn/Status conflicts, {n2} morning-flag conflicts")
    return df


#duplicat removal
def step_8_route_ids_and_duplicates(df, report):

    missing = df["RouteID"].isna()
    n_missing = add_note(df, missing, "Missing RouteID")

    bad_format = df["RouteID"].notna() & ~df["RouteID"].str.match(ROUTE_ID_PATTERN, na=False)
    n_format = add_note(df, bad_format, "RouteID has unexpected format")

    #keep first instance
    exact_dupes = df.duplicated(keep="first") & df["RouteID"].notna()
    removed = int(exact_dupes.sum())
    df = df[~exact_dupes].copy()

    #duplicate section (review)
    dup_ids = df["RouteID"].notna() & df["RouteID"].duplicated(keep=False)
    n_dup = add_note(df, dup_ids, "Duplicate RouteID")

    report.log(f"[8] Route IDs: {n_missing:,} missing, {n_format} bad format, "
               f"{n_dup} duplicated IDs flagged; {removed} exact duplicate rows removed")
    return df.reset_index(drop=True)


#suspicious data check
def step_9_check_coverage(df, report):
 
    dates = pd.to_datetime(df["RouteDate"].dropna().unique())
    if len(dates) == 0:
        return df

 
    all_days = pd.date_range(dates.min(), dates.max())
    missing = all_days.difference(dates)
    ranges, start, prev = [], None, None
    for day in missing:
        if start is None:
            start = prev = day
        elif (day - prev).days == 1:
            prev = day
        else:
            ranges.append((start, prev)); start = prev = day
    if start is not None:
        ranges.append((start, prev))
    text = ", ".join(a.strftime("%Y-%m-%d") if a == b else f"{a:%Y-%m-%d} to {b:%Y-%m-%d}" for a, b in ranges)
    report.log(f"[9] Coverage: {len(missing)} calendar days have no data" + (f" ({text})" if text else ""))

    # No show review flag
    daily = df.groupby("RouteDate").agg(routes=("Status", "size"),
                                         no_shows=("Status", lambda s: int((s == "No Show").sum())))
    daily["rate"] = daily["no_shows"] / daily["routes"]
    bad_days = daily[(daily["routes"] >= MIN_ROUTES_FOR_RATE) & (daily["rate"] >= SUSPICIOUS_NOSHOW_RATE)]
    if len(bad_days):
        n = add_note(df, df["RouteDate"].isin(bad_days.index),
                     f"Suspicious day: {int(SUSPICIOUS_NOSHOW_RATE * 100)}%+ of routes are No Show")
        report.log(f"    ! {len(bad_days)} suspicious days ({n} rows flagged): "
                   f"{bad_days.index.min()} to {bad_days.index.max()}, "
                   f"{int(bad_days['no_shows'].sum())} of {int(bad_days['routes'].sum())} routes are No Show")
        report.log("      -> Review with team before adding 'Unaccounted' data.")
    return df


#Final data columns bits n pieces
FINAL_COLUMNS = [
    "RouteID", "RouteDate", "DayOfWeek", "DriverName", "Status", "CheckedIn",
    "MorningCheckInFlag", "MorningCheckInTime", "ArrivalTime", "ArrivalHour", NOTES_COL,
]


def step_10_finalize(df, report):
    df = df[FINAL_COLUMNS].sort_values(["RouteDate", "RouteID"], na_position="last").reset_index(drop=True)

    flagged = int((df[NOTES_COL] != "").sum())
    with_id = df[df["RouteID"].notna()]
    report.log("[10] Final summary")
    report.log(f"    Clean rows: {len(df):,}   (rows with at least one note: {flagged:,})")
    report.log(f"    Status counts (all rows): {df['Status'].value_counts().to_dict()}")
    report.log(f"    Status counts (rows WITH a RouteID, matches the dashboard KPIs): "
               f"{with_id['Status'].value_counts().to_dict()}  | total={len(with_id):,}")
    if len(df):
        report.log(f"    Date range: {df['RouteDate'].min()} to {df['RouteDate'].max()}")
    return df


def clean(df, report):
    df = step_2_drop_empty_rows(df, report)
    df = step_3_clean_text(df, report)
    df = step_4_fix_dates(df, report)
    df = step_5_fix_arrival(df, report)
    df = step_6_fix_morning_checkin(df, report)
    df = step_7_check_consistency(df, report)
    df = step_8_route_ids_and_duplicates(df, report)
    df = step_9_check_coverage(df, report)
    df = step_10_finalize(df, report)
    return df


#What I see
def save_outputs(df, report, out_dir, make_sqlite):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "cleaned_route_data.csv"
    df.to_csv(csv_path, index=False)
    report.log(f"\nSaved clean data   -> {csv_path}")

    if make_sqlite:
        db_path = out_dir / "routes.db"
        with sqlite3.connect(db_path) as conn:    
            df.to_sql("routes", conn, if_exists="replace", index=False)
        report.log(f"Saved SQLite database -> {db_path}  (table name: routes)")

    report_path = out_dir / "cleaning_report.txt"
    report.log(f"Saved report       -> {report_path}")
    report.save(report_path)


def main():
    parser = argparse.ArgumentParser(description="Clean a delivery-route check-in log.")
    parser.add_argument("input", help="path to the .xlsx or .csv file")
    parser.add_argument("--sheet", default="RawData", help="Excel sheet name (default: RawData)")
    parser.add_argument("--out", default="output", help="folder for results (default: output)")
    parser.add_argument("--sqlite", action="store_true", help="also create a SQLite database")
    args = parser.parse_args()

    report = Report()
    df = step_1_load(args.input, args.sheet, report)
    df = clean(df, report)
    save_outputs(df, report, args.out, args.sqlite)


if __name__ == "__main__":
    main()
