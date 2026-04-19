#!/usr/bin/env python3
"""Build Yahoo! 乗換案内 URL from canonical route fields."""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Protocol, cast
from urllib.parse import urlencode

BASE_URL = "https://transit.yahoo.co.jp/search/result"

TIME_TYPE_MAP = {
    "departure": "1",
    "arrival": "4",
    "first_train": "3",
    "last_train": "2",
    "unspecified": "5",
}

TICKET_MAP = {
    "ic": "ic",
    "cash": "normal",
}

SEAT_MAP = {
    "non_reserved": "1",
    "reserved": "2",
    "green": "3",
}

WALK_MAP = {
    "fast": "1",
    "slightly_fast": "2",
    "slightly_slow": "3",
    "slow": "4",
}

SORT_MAP = {
    "time": "0",
    "fare": "1",
    "transfer": "2",
}


class BuildUrlArgs(Protocol):
    departure: str
    arrival: str
    via: list[str] | None
    year: int | None
    month: int | None
    day: int | None
    hour: int | None
    minute: int | None
    time_type: str
    ticket: str
    seat_preference: str
    walk_speed: str
    sort_by: str
    use_airline: bool
    use_shinkansen: bool
    use_express: bool
    use_highway_bus: bool
    use_local_bus: bool
    use_ferry: bool


def build_url(args: BuildUrlArgs) -> str:
    now = datetime.now()
    year = args.year if args.year is not None else now.year
    month = args.month if args.month is not None else now.month
    day = args.day if args.day is not None else now.day
    hour = args.hour if args.hour is not None else now.hour
    minute = args.minute if args.minute is not None else now.minute

    via = (args.via or [])[:3]

    params: list[tuple[str, str]] = [
        ("from", args.departure),
        ("to", args.arrival),
        ("y", str(year)),
        ("m", f"{month:02d}"),
        ("d", f"{day:02d}"),
        ("hh", str(hour)),
        ("m1", str(minute // 10)),
        ("m2", str(minute % 10)),
        ("type", TIME_TYPE_MAP[args.time_type]),
        ("ticket", TICKET_MAP[args.ticket]),
        ("expkind", SEAT_MAP[args.seat_preference]),
        ("ws", WALK_MAP[args.walk_speed]),
        ("s", SORT_MAP[args.sort_by]),
        ("al", "1" if args.use_airline else "0"),
        ("shin", "1" if args.use_shinkansen else "0"),
        ("ex", "1" if args.use_express else "0"),
        ("hb", "1" if args.use_highway_bus else "0"),
        ("lb", "1" if args.use_local_bus else "0"),
        ("sr", "1" if args.use_ferry else "0"),
    ]

    for station in via:
        params.append(("via", station))

    return f"{BASE_URL}?{urlencode(params)}"


def parse_args() -> BuildUrlArgs:
    parser = argparse.ArgumentParser(
        description="Build a Yahoo! 乗換案内 search URL from route options."
    )
    _ = parser.add_argument(
        "--from", dest="departure", required=True, help="Departure station in Japanese"
    )
    _ = parser.add_argument(
        "--to", dest="arrival", required=True, help="Arrival station in Japanese"
    )
    _ = parser.add_argument(
        "--via", action="append", help="Via station (repeatable, max 3)"
    )

    _ = parser.add_argument("--year", type=int)
    _ = parser.add_argument("--month", type=int)
    _ = parser.add_argument("--day", type=int)
    _ = parser.add_argument("--hour", type=int)
    _ = parser.add_argument("--minute", type=int)

    _ = parser.add_argument(
        "--time-type",
        default="departure",
        choices=sorted(TIME_TYPE_MAP.keys()),
    )
    _ = parser.add_argument(
        "--ticket",
        default="ic",
        choices=sorted(TICKET_MAP.keys()),
    )
    _ = parser.add_argument(
        "--seat-preference",
        default="non_reserved",
        choices=sorted(SEAT_MAP.keys()),
    )
    _ = parser.add_argument(
        "--walk-speed",
        default="slightly_slow",
        choices=sorted(WALK_MAP.keys()),
    )
    _ = parser.add_argument(
        "--sort-by",
        default="time",
        choices=sorted(SORT_MAP.keys()),
    )

    _ = parser.add_argument(
        "--use-airline", action=argparse.BooleanOptionalAction, default=True
    )
    _ = parser.add_argument(
        "--use-shinkansen", action=argparse.BooleanOptionalAction, default=True
    )
    _ = parser.add_argument(
        "--use-express", action=argparse.BooleanOptionalAction, default=True
    )
    _ = parser.add_argument(
        "--use-highway-bus", action=argparse.BooleanOptionalAction, default=True
    )
    _ = parser.add_argument(
        "--use-local-bus", action=argparse.BooleanOptionalAction, default=True
    )
    _ = parser.add_argument(
        "--use-ferry", action=argparse.BooleanOptionalAction, default=True
    )

    return cast(BuildUrlArgs, cast(object, parser.parse_args()))


def main() -> None:
    args = parse_args()
    print(build_url(args))


if __name__ == "__main__":
    main()
