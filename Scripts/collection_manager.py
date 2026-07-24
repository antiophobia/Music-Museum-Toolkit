"""
Music Museum Toolkit
Collection Writer
Version 0.3.1
"""

import os
import re
from numbers import Integral, Real
from datetime import datetime

import pandas as pd


TOOLKIT_VERSION = "0.3.1"
MUSEUM_ID_PATTERN = re.compile(r"^MMT-\d{6}$")
COLLECTION_COLUMNS = [
    "Museum ID", "Source", "Source Track ID", "Title", "Artist", "Album",
    "Release Date", "Duration (ms)", "Popularity", "Spotify URL",
    "Archived At", "Toolkit Version", "Status", "Notes",
]


def _output_path(filename):
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "Output", filename)
    )


def _read_csv_if_present(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame(columns=COLLECTION_COLUMNS)
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=COLLECTION_COLUMNS)


def load_existing_collection():
    return _read_csv_if_present(_output_path("collection.csv"))


def load_checkpoint():
    return _read_csv_if_present(_output_path("collection.checkpoint.csv"))


def build_collection(artifacts, existing=None):
    existing = existing if existing is not None else pd.DataFrame()
    existing_by_id = {}
    if "Source Track ID" in existing.columns:
        existing_by_id = {
            str(row["Source Track ID"]): row
            for _, row in existing.iterrows()
            if str(row.get("Source Track ID", ""))
        }

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for artifact in artifacts:
        track_id = str(artifact.get("Spotify ID", ""))
        old = existing_by_id.get(track_id, {})
        rows.append({
            "Museum ID": old.get("Museum ID", ""),
            "Source": "Spotify",
            "Source Track ID": track_id,
            "Title": artifact.get("Title", old.get("Title", "")),
            "Artist": artifact.get("Artist", old.get("Artist", "")),
            "Album": artifact.get("Album", old.get("Album", "")),
            "Release Date": artifact.get(
                "Release Date", old.get("Release Date", "")
            ),
            "Duration (ms)": artifact.get(
                "Duration (ms)", old.get("Duration (ms)", "")
            ),
            "Popularity": artifact.get("Popularity", old.get("Popularity", "")),
            "Spotify URL": artifact.get(
                "Spotify URL", old.get("Spotify URL", "")
            ),
            "Archived At": old.get("Archived At", now),
            # This field records the version that first created the artifact.
            "Toolkit Version": old.get("Toolkit Version", TOOLKIT_VERSION),
            "Status": old.get("Status", "Available"),
            "Notes": artifact.get("Notes", old.get("Notes", "")),
        })

    used_ids = {
        int(value[4:])
        for value in (row["Museum ID"] for row in rows)
        if isinstance(value, str) and value.startswith("MMT-") and value[4:].isdigit()
    }
    next_id = max(used_ids, default=0) + 1
    for row in rows:
        if not row["Museum ID"]:
            while next_id in used_ids:
                next_id += 1
            row["Museum ID"] = f"MMT-{next_id:06}"
            used_ids.add(next_id)
            next_id += 1

    return pd.DataFrame(rows, columns=COLLECTION_COLUMNS)


def validate_collection(collection, existing=None):
    """Return validation errors without modifying either collection."""
    errors = []
    existing = existing if existing is not None else pd.DataFrame(
        columns=COLLECTION_COLUMNS
    )

    if collection.empty:
        errors.append("resulting collection is unexpectedly empty")
        return errors

    missing_columns = [
        column for column in COLLECTION_COLUMNS if column not in collection.columns
    ]
    if missing_columns:
        errors.append(
            "collection is missing required columns: " + ", ".join(missing_columns)
        )
        return errors

    museum_ids = collection["Museum ID"].fillna("").astype(str)
    if museum_ids.str.strip().eq("").any():
        errors.append("Museum IDs must be present")
    invalid_ids = museum_ids[~museum_ids.str.match(MUSEUM_ID_PATTERN)]
    if not invalid_ids.empty:
        errors.append("Museum IDs must match MMT- followed by six digits")
    if museum_ids.duplicated().any():
        errors.append("Museum IDs must be unique")

    spotify_rows = collection[collection["Source"].eq("Spotify")]
    source_ids = spotify_rows["Source Track ID"].fillna("").astype(str)
    if source_ids.str.strip().eq("").any():
        errors.append("Spotify source track IDs must be present")
    if source_ids[source_ids.ne("")].duplicated().any():
        errors.append("Spotify source track IDs must be unique")

    for field in ("Source", "Title", "Artist", "Album"):
        if collection[field].fillna("").astype(str).str.strip().eq("").any():
            errors.append(f"required identity field {field!r} must be present")

    if not existing.empty:
        old_by_source_id = existing.set_index("Source Track ID", drop=False)
        new_by_source_id = collection.set_index("Source Track ID", drop=False)
        removed = old_by_source_id.index.difference(new_by_source_id.index)
        if len(removed):
            errors.append(
                f"{len(removed)} existing artifact(s) would be unintentionally removed"
            )

        for track_id in old_by_source_id.index.intersection(new_by_source_id.index):
            old = old_by_source_id.loc[track_id]
            new = new_by_source_id.loc[track_id]
            # Duplicate indices are already invalid and cannot be compared safely.
            if isinstance(old, pd.DataFrame) or isinstance(new, pd.DataFrame):
                continue
            for field in ("Museum ID", "Archived At", "Notes"):
                if str(old.get(field, "")) != str(new.get(field, "")):
                    errors.append(
                        f"{field} changed for existing source track {track_id}"
                    )

    return errors


def assert_valid_collection(collection, existing=None):
    """Raise before saving when collection integrity or preservation fails."""
    errors = validate_collection(collection, existing)
    if errors:
        raise ValueError(
            "Collection validation failed:\n- " + "\n- ".join(errors)
        )


def _atomic_save(df, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = path + ".tmp"
    df.to_csv(temporary_path, index=False)
    os.replace(temporary_path, path)


def _semantic_value(value):
    """Normalize CSV representation differences without changing real text."""
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, Real) and float(value).is_integer():
        return str(int(value))
    return str(value)


def _canonical_collection(df):
    """Return a comparison-only view independent of dtype, index, and row order."""
    canonical = df.reindex(columns=COLLECTION_COLUMNS).copy()
    for column in COLLECTION_COLUMNS:
        canonical[column] = canonical[column].map(_semantic_value)
    return canonical.sort_values(
        ["Museum ID", "Source", "Source Track ID"], kind="stable"
    ).reset_index(drop=True)


def collections_semantically_equal(left, right):
    """Compare collection content as it is represented in the CSV schema."""
    if set(left.columns) != set(right.columns):
        return False
    return _canonical_collection(left).equals(_canonical_collection(right))


def save_checkpoint(df):
    path = _output_path("collection.checkpoint.csv")
    _atomic_save(df, path)
    return path


def save_collection(df, existing=None):
    assert_valid_collection(df, existing)
    path = _output_path("collection.csv")
    if os.path.exists(path):
        saved = _read_csv_if_present(path)
        if collections_semantically_equal(saved, df):
            print(f"\nCollection unchanged:\n{path} was validated and not rewritten.")
            return path
    _atomic_save(df, path)
    print(f"\nCollection saved:\n{path}")
    return path


def remove_checkpoint():
    path = _output_path("collection.checkpoint.csv")
    if os.path.exists(path):
        os.remove(path)
