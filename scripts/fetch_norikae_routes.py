#!/usr/bin/env python3
"""Fetch and extract Yahoo! 乗換案内 route content."""

from __future__ import annotations

import argparse
from datetime import datetime
import html as html_lib
import re
import sys
from typing import Protocol, cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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


class _BuildUrlArgs(Protocol):
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


class _MainArgs(_BuildUrlArgs, Protocol):
    url: str | None
    timeout: int


def build_url(args: _BuildUrlArgs) -> str:
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


def fetch_html(url: str, timeout: int) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            )
        },
    )
    with urlopen(request, timeout=timeout) as resp:  # pyright: ignore[reportAny]
        charset = cast(str, resp.headers.get_content_charset()) or "utf-8"  # pyright: ignore[reportAny]
        raw = cast(bytes, resp.read())  # pyright: ignore[reportAny]
        return raw.decode(charset, errors="ignore")


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", "", fragment)
    return html_lib.unescape(text).strip()


def _extract_summary(block: str) -> str:
    m = re.search(r'<ul class="summary">(.*?)</ul>', block, re.S)
    if not m:
        return ""
    ul = m.group(1)
    items = cast(
        list[tuple[str, str]],
        re.findall(r'<li class="(\w+)"[^>]*>(.*?)</li>', ul, re.S),
    )
    parts: list[str] = []
    for _cls, content in items:
        parts.append(re.sub(r"\s+", " ", _strip_tags(content)))
    return " | ".join(parts)


def _parse_route_detail(block: str) -> list[str]:
    lines: list[str] = []

    # Find station and access elements in document order
    elements = list(
        re.finditer(
            r'<div class="(station|access[^"]*)"[^>]*>',
            block,
        )
    )

    for i, elem in enumerate(elements):
        kind = elem.group(1)
        start = elem.start()
        end = elements[i + 1].start() if i + 1 < len(elements) else len(block)
        chunk = block[start:end]

        if kind == "station":
            time_m = re.search(r'<ul class="time">(.*?)</ul>', chunk, re.S)
            time_parts: list[str] = []
            if time_m:
                time_parts = [
                    _strip_tags(cast(str, t))
                    for t in re.findall(r"<li>(.*?)</li>", time_m.group(1))  # pyright: ignore[reportAny]
                ]
            time_str = " / ".join(time_parts)

            name = ""
            name_m = re.search(r"<dt>(?:<a[^>]*>)?(.*?)(?:</a>)?</dt>", chunk, re.S)
            if name_m:
                name = _strip_tags(name_m.group(1))

            if re.search(r"icnStaDep", chunk):
                prefix = "[発]"
            elif re.search(r"icnStaArr", chunk):
                prefix = "[着]"
            else:
                prefix = "   "

            lines.append(f"  {prefix} {time_str}  {name}")

        elif kind.startswith("access"):
            if re.search(r"icnWalk", chunk):
                lines.append("    | 徒歩")
            else:
                transport_m = re.search(
                    r'<li class="transport"[^>]*>(.*?)</li>', chunk, re.S
                )
                if transport_m:
                    inner = transport_m.group(1)
                    # Extract destination separately (handle nested spans)
                    dest_parts: list[str] = []
                    dest_m = re.search(
                        r'<span class="destination">(.*)</span></div>', inner, re.S
                    )
                    if dest_m:
                        dest_html = dest_m.group(1)
                        # Remove "当駅始発" marker
                        dest_html = re.sub(
                            r'<span class="icnFirstTrain">[^<]*</span>', "", dest_html
                        )
                        dest_text = _strip_tags(dest_html)
                        if dest_text:
                            dest_parts.append(dest_text)
                        inner = inner[: dest_m.start()] + inner[dest_m.end() :]
                    # Remove line color span and icon spans
                    inner = re.sub(r'<span class="line[^"]*"[^>]*></span>', "", inner)
                    transport = re.sub(r"\s+", " ", _strip_tags(inner)).strip()
                    dest_str = f" ({', '.join(dest_parts)})" if dest_parts else ""
                    lines.append(f"    | {transport}{dest_str}")

                # Fare follows the access div as <p class="fare">
                fare_m = re.search(r'<p class="fare"[^>]*>(.*?)</p>', chunk, re.S)
                if fare_m:
                    lines.append(f"    | 運賃: {_strip_tags(fare_m.group(1))}")

    return lines


def extract_content(html: str) -> str:
    cleaned = re.sub(r"<!--.*?-->", "", html, flags=re.S)

    route_blocks = cast(
        list[tuple[str, str]],
        re.findall(
            r'id="route(\d+)"[^>]*>(.*?)(?=<div[^>]*id="route\d+"|<div[^>]*id="mdRouteSearch")',
            cleaned,
            re.S,
        ),
    )

    if not route_blocks:
        text = re.sub(r"<[^>]+>", "\n", cleaned)
        text = html_lib.unescape(text)
        text = re.sub(r"\n\s*\n+", "\n", text).strip()
        start = text.find("ルート1")
        end = text.find("条件を変更して検索")
        if start != -1 and end != -1:
            return text[start:end].strip()
        return text

    routes: list[str] = []
    for idx_str, block in route_blocks:
        idx = int(idx_str)
        lines: list[str] = [f"=== ルート{idx} ==="]
        summary = _extract_summary(block)
        if summary:
            lines.append(summary)
        lines.append("")

        detail_m = re.search(r'<div class="routeDetail">(.*)', block, re.S)
        if detail_m:
            lines.extend(_parse_route_detail(detail_m.group(1)))

        routes.append("\n".join(lines))

    return "\n\n".join(routes)


def parse_args() -> _MainArgs:
    parser = argparse.ArgumentParser(
        description="Fetch and extract route details from Yahoo! 乗換案内."
    )

    _ = parser.add_argument("--url", help="Fully prepared Yahoo transit URL")
    _ = parser.add_argument(
        "--from", dest="departure", help="Departure station in Japanese"
    )
    _ = parser.add_argument("--to", dest="arrival", help="Arrival station in Japanese")
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

    _ = parser.add_argument("--timeout", type=int, default=20)

    result = cast(_MainArgs, cast(object, parser.parse_args()))

    if not result.url and (not result.departure or not result.arrival):
        parser.error("Provide --url, or both --from and --to.")

    return result


def main() -> int:
    args = parse_args()
    url = args.url or build_url(args)

    try:
        html = fetch_html(url, args.timeout)
        content = extract_content(html)
    except Exception as exc:  # pragma: no cover - network/runtime failures
        print(f"Error fetching route data: {exc}", file=sys.stderr)
        return 1

    print(f"URL: {url}")
    print()
    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
