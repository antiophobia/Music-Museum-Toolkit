"""Occurrence-level Spotify playlist manifest storage and validation."""

import os
from numbers import Integral, Real

import pandas as pd


MANIFEST_VERSION = "1"
MANIFEST_COLUMNS = [
    "Manifest Version",
    "Playlist ID",
    "Playlist Name",
    "Snapshot ID",
    "Captured At",
    "Playlist Position",
    "Classification",
    "Restorable",
    "Museum ID",
    "Source Track ID",
    "Spotify URI",
    "Title",
    "Artist",
    "Album",
    "Added At",
    "Duplicate Of Position",
    "Reason",
]
CLASSIFICATIONS = {
    "valid track",
    "duplicate occurrence",
    "local file",
    "unavailable entry",
    "unsupported entry",
    "malformed entry",
}
REPORT_CLASSIFICATIONS = {
    "valid_tracks": "valid track",
    "duplicate_tracks": "duplicate occurrence",
    "local_files": "local file",
    "unavailable_entries": "unavailable entry",
    "unsupported_entries": "unsupported entry",
    "malformed_entries": "malformed entry",
}


def _output_path(filename):
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "Output", filename)
    )


def _read(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame(columns=MANIFEST_COLUMNS)
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=MANIFEST_COLUMNS)


def load_manifest():
    return _read(_output_path("playlist_manifest.csv"))


def load_manifest_checkpoint():
    return _read(_output_path("playlist_manifest.checkpoint.csv"))


def _text(value):
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, Real) and float(value).is_integer():
        return str(int(value))
    return str(value)


def _canonical(manifest):
    result = manifest.reindex(columns=MANIFEST_COLUMNS).copy()
    for column in MANIFEST_COLUMNS:
        result[column] = result[column].map(_text)
    return result.reset_index(drop=True)


def manifests_semantically_equal(left, right):
    if set(left.columns) != set(right.columns):
        return False
    return _canonical(left).equals(_canonical(right))


def map_museum_ids(manifest, collection):
    """Map valid and duplicate Spotify occurrences to permanent Museum IDs."""
    result = manifest.reindex(columns=MANIFEST_COLUMNS).copy()
    museum_by_source = {
        _text(row.get("Source Track ID")): _text(row.get("Museum ID"))
        for _, row in collection.iterrows()
        if _text(row.get("Source Track ID"))
    }
    occurrence_mask = result["Classification"].isin(
        ["valid track", "duplicate occurrence"]
    )
    result.loc[occurrence_mask, "Museum ID"] = result.loc[
        occurrence_mask, "Source Track ID"
    ].map(museum_by_source).fillna("")
    return result


def validate_manifest(
    manifest,
    collection,
    playlist_id,
    playlist_name,
    snapshot_id,
    report,
):
    """Return all manifest integrity errors without modifying the manifest."""
    errors = []
    scanned = int(report.get("playlist_entries_scanned", 0))

    missing = [column for column in MANIFEST_COLUMNS if column not in manifest]
    if missing:
        return ["manifest is missing required columns: " + ", ".join(missing)]
    if scanned and manifest.empty:
        errors.append("manifest is empty for a nonempty scanned playlist")
    if len(manifest) != scanned:
        errors.append(
            f"manifest row count {len(manifest)} does not match "
            f"{scanned} entries scanned"
        )

    positions = pd.to_numeric(manifest["Playlist Position"], errors="coerce")
    if positions.isna().any():
        errors.append("playlist positions must be present and numeric")
    else:
        integer_positions = positions.astype(int)
        if not positions.eq(integer_positions).all():
            errors.append("playlist positions must be whole numbers")
        if integer_positions.duplicated().any():
            errors.append("playlist positions must be unique")
        if integer_positions.tolist() != list(range(1, len(manifest) + 1)):
            errors.append("playlist positions must be contiguous and ordered from 1")

    unknown = set(manifest["Classification"].map(_text)) - CLASSIFICATIONS
    if unknown:
        errors.append("manifest contains unknown classifications: " + ", ".join(
            sorted(unknown)
        ))

    expected_identity = {
        "Manifest Version": MANIFEST_VERSION,
        "Playlist ID": playlist_id,
        "Playlist Name": playlist_name,
        "Snapshot ID": snapshot_id,
    }
    for column, expected in expected_identity.items():
        if not manifest[column].map(_text).eq(_text(expected)).all():
            errors.append(f"manifest has inconsistent {column}")
    if len(manifest) and manifest["Captured At"].map(_text).eq("").any():
        errors.append("manifest Captured At must be present")
    if len(manifest) and manifest["Captured At"].map(_text).nunique() != 1:
        errors.append("manifest Captured At must be consistent")

    collection_map = {
        _text(row.get("Source Track ID")): _text(row.get("Museum ID"))
        for _, row in collection.iterrows()
        if _text(row.get("Source Track ID"))
    }
    first_positions = {}
    for index, row in manifest.iterrows():
        classification = _text(row["Classification"])
        source_id = _text(row["Source Track ID"])
        museum_id = _text(row["Museum ID"])
        restorable_text = _text(row["Restorable"])
        restorable = restorable_text.lower() == "true"
        position = index + 1

        if restorable_text not in {"True", "False"}:
            errors.append(
                f"Restorable at position {position} must be True or False"
            )
        if restorable and (
            classification not in {"valid track", "duplicate occurrence"}
            or not source_id
        ):
            errors.append(
                f"restorable row at position {position} lacks usable track identity"
            )
        if classification in {"valid track", "duplicate occurrence"}:
            if not source_id or source_id not in collection_map:
                errors.append(
                    f"Spotify occurrence at position {position} cannot be mapped "
                    "to the candidate collection"
                )
            elif museum_id != collection_map[source_id]:
                errors.append(
                    f"Museum ID at position {position} does not match the collection"
                )
            if not restorable:
                errors.append(
                    f"Spotify occurrence at position {position} must be restorable"
                )
        elif restorable:
            errors.append(
                f"non-track occurrence at position {position} cannot be restorable"
            )
        if (
            classification
            in {
                "local file",
                "unavailable entry",
                "unsupported entry",
                "malformed entry",
            }
            and not _text(row["Reason"])
        ):
            errors.append(
                f"nonrestorable occurrence at position {position} needs a reason"
            )

        if classification == "valid track":
            if source_id in first_positions:
                errors.append(
                    f"valid track at position {position} repeats an earlier source ID"
                )
            else:
                first_positions[source_id] = position
            if _text(row["Duplicate Of Position"]):
                errors.append(
                    f"valid track at position {position} cannot link as a duplicate"
                )
        elif classification == "duplicate occurrence":
            link_text = _text(row["Duplicate Of Position"])
            try:
                link = int(link_text)
            except ValueError:
                link = 0
            expected = first_positions.get(source_id)
            if not expected or link != expected or link >= position:
                errors.append(
                    f"duplicate at position {position} does not point backward "
                    "to the correct first occurrence"
                )

    actual_counts = manifest["Classification"].value_counts().to_dict()
    for report_key, classification in REPORT_CLASSIFICATIONS.items():
        if int(report.get(report_key, 0)) != int(actual_counts.get(classification, 0)):
            errors.append(
                f"manifest {classification!r} total does not match final scan report"
            )
    return errors


def assert_valid_manifest(*args, **kwargs):
    errors = validate_manifest(*args, **kwargs)
    if errors:
        raise ValueError("Manifest validation failed:\n- " + "\n- ".join(errors))


def validate_manifest_checkpoint(
    manifest, playlist_id, playlist_name, snapshot_id, report
):
    """Return whether checkpoint rows and saved report are safe to resume."""
    if any(column not in manifest for column in MANIFEST_COLUMNS):
        return False

    try:
        expected_rows = int(report.get("playlist_entries_scanned", 0))
        report_counts = {
            report_key: int(report.get(report_key, 0))
            for report_key in REPORT_CLASSIFICATIONS
        }
    except (AttributeError, TypeError, ValueError):
        return False
    if len(manifest) != expected_rows:
        return False

    positions = pd.to_numeric(manifest["Playlist Position"], errors="coerce")
    if positions.isna().any():
        return False
    integer_positions = positions.astype(int)
    if not positions.eq(integer_positions).all():
        return False
    if integer_positions.duplicated().any():
        return False
    if integer_positions.tolist() != list(range(1, len(manifest) + 1)):
        return False

    if manifest.empty:
        return all(count == 0 for count in report_counts.values())

    expected_identity = {
        "Manifest Version": MANIFEST_VERSION,
        "Playlist ID": playlist_id,
        "Playlist Name": playlist_name,
        "Snapshot ID": snapshot_id,
    }
    if any(
        not manifest[column].map(_text).eq(_text(expected)).all()
        for column, expected in expected_identity.items()
    ):
        return False

    captured_at = manifest["Captured At"].map(_text)
    if captured_at.eq("").any() or captured_at.nunique() != 1:
        return False

    classifications = manifest["Classification"].map(_text)
    if not set(classifications).issubset(CLASSIFICATIONS):
        return False
    if not manifest["Restorable"].map(_text).isin({"True", "False"}).all():
        return False

    first_positions = {}
    for index, row in manifest.iterrows():
        position = index + 1
        classification = _text(row["Classification"])
        source_id = _text(row["Source Track ID"])
        restorable = _text(row["Restorable"]) == "True"
        if classification in {"valid track", "duplicate occurrence"}:
            if not source_id or not restorable:
                return False
        elif restorable:
            return False

        if classification == "valid track":
            if source_id in first_positions or _text(row["Duplicate Of Position"]):
                return False
            first_positions[source_id] = position
        elif classification == "duplicate occurrence":
            duplicate_text = _text(row["Duplicate Of Position"])
            try:
                duplicate_position = int(duplicate_text)
            except ValueError:
                return False
            expected = first_positions.get(source_id)
            if (
                not expected
                or duplicate_position != expected
                or duplicate_position >= position
            ):
                return False

    actual_counts = classifications.value_counts().to_dict()
    return all(
        report_counts[report_key] == int(actual_counts.get(classification, 0))
        for report_key, classification in REPORT_CLASSIFICATIONS.items()
    )


def _atomic_save(manifest, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = path + ".tmp"
    manifest.reindex(columns=MANIFEST_COLUMNS).to_csv(temporary_path, index=False)
    os.replace(temporary_path, path)


def save_manifest_checkpoint(manifest):
    path = _output_path("playlist_manifest.checkpoint.csv")
    _atomic_save(manifest, path)
    return path


def save_manifest(
    manifest, collection, playlist_id, playlist_name, snapshot_id, report
):
    assert_valid_manifest(
        manifest, collection, playlist_id, playlist_name, snapshot_id, report
    )
    path = _output_path("playlist_manifest.csv")
    if os.path.exists(path):
        saved = _read(path)
        if manifests_semantically_equal(saved, manifest):
            print(f"\nPlaylist manifest unchanged:\n{path} was validated and not rewritten.")
            return path
    _atomic_save(manifest, path)
    print(f"\nPlaylist manifest saved:\n{path}")
    return path


def remove_manifest_checkpoint():
    path = _output_path("playlist_manifest.checkpoint.csv")
    if os.path.exists(path):
        os.remove(path)
