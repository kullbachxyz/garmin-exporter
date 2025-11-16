#!/usr/bin/env python3
"""Interactive Garmin Connect exporter.

This script logs in to a Garmin Connect account and downloads FIT files for the
selected activity types. It relies on the ``garminconnect`` package for the
heavy lifting (install with ``pip install garminconnect``).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile
from getpass import getpass
from pathlib import Path
from typing import Iterable, List, Sequence, Set

Garmin: object | None = None
GARMINCONNECT_IMPORT_ERROR: Exception | None = None
try:
    from garminconnect import Garmin as GarminClass  # type: ignore

    Garmin = GarminClass
except ImportError as exc:  # pragma: no cover - dependency missing at runtime
    GARMINCONNECT_IMPORT_ERROR = exc

try:
    from garminconnect import (  # type: ignore
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarminConnectTooManyRequestsError,
    )
except ImportError:  # pragma: no cover - fall back to generic exceptions
    GarminConnectAuthenticationError = GarminConnectConnectionError = GarminConnectTooManyRequestsError = Exception

try:
    from garminconnect import ActivityDownloadFormat  # type: ignore
except ImportError:  # pragma: no cover
    ActivityDownloadFormat = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Garmin activities as FIT files.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--username",
        help="Garmin username. Defaults to $GARMIN_USERNAME or interactive prompt.",
    )
    parser.add_argument(
        "--password",
        help="Garmin password. Defaults to $GARMIN_PASSWORD or hidden prompt.",
    )
    parser.add_argument(
        "--output",
        default="./activities",
        help="Directory where FIT files will be written.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of activities fetched per API request.",
    )
    parser.add_argument(
        "--max-activities",
        type=int,
        help="Stop after fetching this many activities (defaults to every activity).",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip downloads when the destination FIT file already exists.",
    )
    return parser.parse_args()


def resolve_credentials(args: argparse.Namespace) -> tuple[str, str]:
    username = args.username or os.getenv("GARMIN_USERNAME") or input("Garmin username: ")
    password = args.password or os.getenv("GARMIN_PASSWORD") or getpass("Garmin password: ")
    return username.strip(), password.strip()


def fetch_all_activities(
    client: "Garmin",
    batch_size: int,
    max_activities: int | None = None,
) -> List[dict]:
    activities: List[dict] = []
    start = 0
    while True:
        chunk = client.get_activities(start, batch_size)
        if not chunk:
            break
        activities.extend(chunk)
        start += batch_size
        if max_activities and len(activities) >= max_activities:
            activities = activities[:max_activities]
            break
        print(f"Fetched {len(activities)} activities so far...", file=sys.stderr)
    return activities


def prompt_activity_types(activity_types: Sequence[str]) -> Set[str]:
    if not activity_types:
        print("No activity types detected; exporting every activity.")
        return set()

    print("\nAvailable activity types:")
    for index, activity_type in enumerate(activity_types, start=1):
        print(f"  {index:>2}: {activity_type}")

    while True:
        choice = input(
            "Enter comma-separated numbers to export, or 'all' to download every type [all]: "
        ).strip()
        if not choice or choice.lower() in {"all", "*"}:
            return set(activity_types)

        try:
            indexes = {int(value) for value in choice.split(",")}
        except ValueError:
            print("Invalid entry. Please use comma-separated numbers or 'all'.")
            continue

        invalid_indexes = [value for value in indexes if value < 1 or value > len(activity_types)]
        if invalid_indexes:
            print(f"Indexes out of range: {', '.join(map(str, invalid_indexes))}")
            continue

        return {activity_types[index - 1] for index in indexes}


def sanitize_name(name: str) -> str:
    cleaned = [
        char.lower() if char.isalnum() else "-"
        for char in name.strip().replace(" ", "-")
    ]
    return "".join(cleaned).strip("-") or "activity"


def download_fit_blob(client: "Garmin", activity_id: int) -> bytes:
    """Request the FIT blob for an activity via garminconnect."""
    if hasattr(client, "download_activity_fit"):
        return client.download_activity_fit(activity_id)

    if ActivityDownloadFormat is not None:
        try:
            return client.download_activity(activity_id, ActivityDownloadFormat.FIT)  # type: ignore[attr-defined]
        except TypeError:
            # Some releases expect a keyword argument instead of a positional flag.
            return client.download_activity(activity_id, file_format=ActivityDownloadFormat.FIT)

    # Fall back to the legacy signature.
    try:
        return client.download_activity(activity_id, "fit")
    except TypeError:
        return client.download_activity(activity_id, file_format="fit")


def extract_fit_bytes(payload: bytes) -> bytes:
    """Extract the FIT payload from a Garmin download response."""
    if payload.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for name in archive.namelist():
                if name.lower().endswith(".fit"):
                    return archive.read(name)
            raise RuntimeError("Downloaded zip file does not contain a FIT payload.")
    return payload


def write_fit_file(destination: Path, payload: bytes) -> None:
    destination.write_bytes(extract_fit_bytes(payload))
    print(f"Wrote {destination}")


def build_destination_path(activity: dict, output_dir: Path) -> Path:
    activity_id = activity.get("activityId", "unknown")
    name = sanitize_name(activity.get("activityName", f"activity-{activity_id}"))
    return output_dir / f"{activity_id}_{name}.fit"


def filter_activities_by_type(
    activities: Iterable[dict],
    wanted_types: Set[str] | None,
) -> List[dict]:
    if not wanted_types:
        return list(activities)

    filtered: List[dict] = []
    for activity in activities:
        type_key = (activity.get("activityType") or {}).get("typeKey")
        if type_key in wanted_types:
            filtered.append(activity)
    return filtered


def export_activities(args: argparse.Namespace) -> None:
    if Garmin is None:
        print(
            "The 'garminconnect' package is required. Install it with 'pip install garminconnect'.",
            file=sys.stderr,
        )
        if GARMINCONNECT_IMPORT_ERROR:
            raise SystemExit(str(GARMINCONNECT_IMPORT_ERROR))
        raise SystemExit(1)

    username, password = resolve_credentials(args)

    try:
        client = Garmin(username, password)
        client.login()
    except GarminConnectAuthenticationError as exc:
        print("Authentication failed. Check your credentials and 2FA settings.", file=sys.stderr)
        raise SystemExit(str(exc))
    except (GarminConnectConnectionError, GarminConnectTooManyRequestsError) as exc:
        print("Unable to connect to Garmin Connect right now.", file=sys.stderr)
        raise SystemExit(str(exc))

    activities = fetch_all_activities(client, args.batch_size, args.max_activities)
    if not activities:
        print("No activities returned by Garmin Connect.")
        return

    type_keys = sorted({
        (activity.get("activityType") or {}).get("typeKey")
        for activity in activities
        if activity.get("activityType")
    })

    selected_types = prompt_activity_types(type_keys)
    filtered = filter_activities_by_type(activities, selected_types)
    if not filtered:
        print("No activities matched the selected type filters.")
        return

    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    for activity in filtered:
        destination = build_destination_path(activity, output_dir)
        if args.skip_existing and destination.exists():
            print(f"Skipping existing file {destination}")
            continue

        activity_id = activity.get("activityId")
        if activity_id is None:
            print(f"Skipping activity without an ID: {json.dumps(activity, default=str)[:80]}...", file=sys.stderr)
            continue

        payload = download_fit_blob(client, activity_id)
        write_fit_file(destination, payload)

    print(f"\nExported {len(filtered)} activities to {output_dir}")


def main() -> None:
    args = parse_args()
    export_activities(args)


if __name__ == "__main__":
    main()
