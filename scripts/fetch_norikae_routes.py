#!/usr/bin/env python3
"""Fetch and extract Yahoo! 乗換案内 route content."""

from __future__ import annotations

import argparse
from datetime import datetime
import html as html_lib
import re
import sys
from typing import Protocol, TypedDict, cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://transit.yahoo.co.jp/search/result"

# ── ANSI colors (disabled when stdout is not a tty) ───


def _use_color() -> bool:
    return sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    if not _use_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def _bold(text: str) -> str:
    return _c("1", text)


def _dim(text: str) -> str:
    return _c("2", text)


def _green(text: str) -> str:
    return _c("32", text)


def _cyan(text: str) -> str:
    return _c("36", text)


def _yellow(text: str) -> str:
    return _c("33", text)


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
    stations: list[str]
    date: str | None
    hour: int | None
    minute: int | None
    time_type: str
    ticket: str
    seat_preference: str
    walk_speed: str
    sort_by: str
    no_airline: bool
    no_shinkansen: bool
    no_express: bool
    no_highway_bus: bool
    no_local_bus: bool
    no_ferry: bool


class _MainArgs(_BuildUrlArgs, Protocol):
    url: str | None
    timeout: int
    show_middle: bool
    page: int


def build_url(args: _BuildUrlArgs) -> str:
    now = datetime.now()

    if args.date:
        parts = args.date.split("/")
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
    else:
        year, month, day = now.year, now.month, now.day

    hour = args.hour if args.hour is not None else now.hour
    minute = args.minute if args.minute is not None else now.minute

    departure = args.stations[0]
    arrival = args.stations[-1]
    via = args.stations[1:-1][:3]

    params: list[tuple[str, str]] = [
        ("from", departure),
        ("to", arrival),
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
        ("al", "0" if args.no_airline else "1"),
        ("shin", "0" if args.no_shinkansen else "1"),
        ("ex", "0" if args.no_express else "1"),
        ("hb", "0" if args.no_highway_bus else "1"),
        ("lb", "0" if args.no_local_bus else "1"),
        ("sr", "0" if args.no_ferry else "1"),
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
        text = re.sub(r"\s+", " ", _strip_tags(content))
        # "04:55発→05:36着41分（乗車41分）" → "04:55 → 05:36 41分 (乗車41分)"
        text = re.sub(
            r"(\d{2}:\d{2})発→(\d{2}:\d{2})着",
            r"\1🡒 \2 ",
            text,
        )
        text = text.replace("（", "(").replace("）", ")")
        parts.append(text)
    # Split into two lines: time + transfers, then fare + distance
    transfer_idx = next((i for i, p in enumerate(parts) if "乗換" in p), len(parts) - 1)
    line1 = " | ".join(parts[: transfer_idx + 1])
    # Highlight time range + total duration, dim the rest but keep transfer count normal
    line1 = re.sub(
        r"^(\d{2}:\d{2}🡒 \d{2}:\d{2} [^\s(]+)\s*(\(.*?\))?(.*?)(乗換：)(\S+)(.*)",
        lambda m: (
            _bold(_yellow(m.group(1)))
            + (" " + _dim(m.group(2)) if m.group(2) else "")
            + _dim(m.group(3))
            + _dim(m.group(4))
            + _yellow(m.group(5))
            + _dim(m.group(6))
        ),
        line1,
    )
    line2_parts = parts[transfer_idx + 1 :]
    if line2_parts:
        # Highlight total fare amount, dim the rest
        fare_part = line2_parts[0] if line2_parts else ""
        fare_part = re.sub(
            r"(.*?)(\d[\d,]+円)\s*(\(.*?\))?",
            lambda m: (
                _dim(m.group(1))
                + _yellow(m.group(2))
                + (" " + _dim(m.group(3)) if m.group(3) else "")
            ),
            fare_part,
            count=1,
        )
        rest = [_dim(p) for p in line2_parts[1:]]
        line2 = (_dim(" | ")).join([fare_part] + rest)
        return f"{line1}\n{line2}"
    return line1


class _RouteDetail(TypedDict):
    lines: list[str]
    fare_sections: list[str]


def _parse_route_detail(block: str, *, show_middle: bool = False) -> _RouteDetail:
    lines: list[str] = []
    fare_sections: list[str] = []

    # Track station names for fare section labels
    fare_section_start = ""
    # Deferred base fare text — resolved when the next station is encountered
    pending_fare: str | None = None
    pending_fare_mode: str = ""
    # Walk resets fare section — next station becomes the new section start
    after_walk = False
    # Track last departure time for interval calculation
    last_dep_minutes: int | None = None

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

            name = ""
            name_m = re.search(r"<dt>(?:<a[^>]*>)?(.*?)(?:</a>)?</dt>", chunk, re.S)
            if name_m:
                name = _strip_tags(name_m.group(1))
                # Strip bus company suffix like "/十王自動車"
                name = re.sub(r"/[^/]+$", "", name)

            station_id = ""
            sid_m = re.search(r'href="/station/(\d+)"', chunk)
            if sid_m:
                station_id = f" [id={sid_m.group(1)}]"

            # Resolve pending base fare now that we know the end station
            if pending_fare is not None:
                # Strip parenthetical suffixes from station names for brevity
                fs = re.sub(r"\(.*?\)", "", fare_section_start).strip()
                ne = re.sub(r"\(.*?\)", "", name).strip()
                fare_sections.append(f"{fs}🡒 ({pending_fare_mode}{pending_fare}) {ne}")
                fare_section_start = name
                pending_fare = None
                pending_fare_mode = ""

            if not fare_section_start or after_walk:
                fare_section_start = name
                after_walk = False

            # Format: " arr ◉ dep  name [id]" with ◉ aligned
            if len(time_parts) == 2:
                arr = time_parts[0].rstrip("着")
                dep = time_parts[1].rstrip("発")
                lines.append(f" {arr} ◉ {dep}  {_bold(_green(name))}{_dim(station_id)}")
                h, m = dep.split(":")
                last_dep_minutes = int(h) * 60 + int(m)
            elif time_parts:
                t = time_parts[0].rstrip("着発")
                lines.append(f"       ◉ {t}  {_bold(_green(name))}{_dim(station_id)}")
                h, m = t.split(":")
                last_dep_minutes = int(h) * 60 + int(m)

        elif kind.startswith("access"):
            # Compute interval by looking ahead to next station's arrival
            dur_str = ""
            if last_dep_minutes is not None:
                for j in range(i + 1, len(elements)):
                    if elements[j].group(1) == "station":
                        next_start = elements[j].start()
                        next_end = (
                            elements[j + 1].start()
                            if j + 1 < len(elements)
                            else len(block)
                        )
                        next_chunk = block[next_start:next_end]
                        next_time_m = re.search(
                            r'<ul class="time">(.*?)</ul>', next_chunk, re.S
                        )
                        if next_time_m:
                            next_times = [
                                _strip_tags(t)
                                for t in cast(
                                    list[str],
                                    re.findall(
                                        r"<li>(.*?)</li>",
                                        next_time_m.group(1),
                                    ),
                                )
                            ]
                            if next_times:
                                arr_t = next_times[0].rstrip("着発")
                                ah, am = arr_t.split(":")
                                arr_min = int(ah) * 60 + int(am)
                                diff = arr_min - last_dep_minutes
                                if diff < 0:
                                    diff += 24 * 60
                                dur_str = f"({diff})"
                        break
            # Pad duration to 6 chars so content aligns at column 16
            dur_pad = f"{dur_str:>6}  " if dur_str else "        "

            if re.search(r"icnWalk", chunk):
                lines.append(f"       │{_dim(dur_pad)}{_dim('徒歩')}")
                after_walk = True
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

                    # Platform info
                    platform_m = re.search(
                        r'<li class="platform">(.*?)</li>', chunk, re.S
                    )
                    platform_suffix = ""
                    if platform_m:
                        raw = re.sub(r"<!--.*?-->", "", platform_m.group(1))
                        raw = _strip_tags(raw).strip()
                        # e.g. "[発] 9番線 → [着] 情報なし"
                        parts_p = [
                            p.strip()
                            for p in re.split(r"→", raw)
                            if "情報なし" not in p and p.strip()
                        ]
                        if parts_p:
                            platform_suffix = f" {_dim('(' + '🡒 '.join(parts_p) + ')')}"

                    # Fare elements — may have surcharge + base fare
                    fare_suffix = ""
                    for fare_m in re.finditer(
                        r'<p class="fare"[^>]*>(.*?)</p>', chunk, re.S
                    ):
                        fare_text = _strip_tags(fare_m.group(1))
                        if not fare_text:
                            continue
                        if re.search(r"指定席|グリーン|自由席", fare_text):
                            fare_suffix += f" {_yellow('[' + fare_text + ']')}"
                        else:
                            pending_fare = fare_text
                            if re.search(r"icn\w*Bus", chunk):
                                pending_fare_mode = "バス "
                            elif re.search(r"icn\w*Ship", chunk):
                                pending_fare_mode = "フェリー "
                            else:
                                pending_fare_mode = ""

                    mode_prefix = ""
                    if re.search(r"icn\w*Bus", chunk):
                        mode_prefix = _dim("バス ")
                    elif re.search(r"icn\w*Ship", chunk):
                        mode_prefix = _dim("フェリー ")

                    lines.append(
                        f"       │{_dim(dur_pad)}{mode_prefix}{_cyan(transport)}{_dim(dest_str)}{platform_suffix}{fare_suffix}"
                    )

                    # Intermediate stations
                    if show_middle:
                        stop_m = re.search(
                            r'<li class="stop">(.*?)</ul></li>',
                            chunk,
                            re.S,
                        )
                        if stop_m:
                            stops = cast(
                                list[tuple[str, str]],
                                re.findall(
                                    r"<dt>(.*?)</dt><dd>.*?</span>(.*?)</dd>",
                                    stop_m.group(1),
                                ),
                            )
                            for time_val, sname in stops:
                                lines.append(
                                    f"       │        {_dim('┊')} {_dim(time_val)}  {_dim(_strip_tags(sname))}"
                                )

    return {"lines": lines, "fare_sections": fare_sections}


def extract_content(html: str, *, show_middle: bool = False) -> str:
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
        # Convert to fullwidth digit
        fw_idx = "".join(chr(ord("０") + int(c)) for c in str(idx))
        lines: list[str] = [_bold(f"◉ ルート{fw_idx}"), ""]
        summary = _extract_summary(block)
        if summary:
            lines.append(summary)
        lines.append("")

        detail_m = re.search(r'<div class="routeDetail">(.*)', block, re.S)
        if detail_m:
            detail = _parse_route_detail(detail_m.group(1), show_middle=show_middle)
            if len(detail["fare_sections"]) > 1 and summary:
                # Compact consecutive sections: "A🡒 (100円)B🡒 (200円)C"
                fs = detail["fare_sections"]
                result = fs[0]
                for j in range(1, len(fs)):
                    # Each section is "start🡒 (fare)end"
                    prev_after = fs[j - 1].split("🡒 ", 1)[1]
                    prev_end = re.sub(r"^\([^)]*\)\s*", "", prev_after)
                    curr_start = fs[j].split("🡒 ", 1)[0]
                    if prev_end == curr_start:
                        result += "🡒 " + fs[j].split("🡒 ", 1)[1]
                    else:
                        result += " | " + fs[j]
                colored = re.sub(
                    r"(\([^)]*\))|([^()]+)",
                    lambda m: _yellow(m.group(1)) if m.group(1) else _dim(m.group(2)),
                    result,
                )
                lines[2] += f" {_dim('|')} {colored}"
            lines.extend(detail["lines"])

        routes.append("\n".join(lines))

    return "\n\n".join(routes)


def parse_args() -> _MainArgs:
    parser = argparse.ArgumentParser(
        description="Fetch and extract route details from Yahoo! 乗換案内.",
    )

    _ = parser.add_argument("--url", help="Fully prepared Yahoo transit URL")
    _ = parser.add_argument(
        "stations",
        nargs="*",
        help="from [via ...] to — departure, optional via stations, then arrival",
    )

    _ = parser.add_argument("--date", help="Date as YYYY/MM/DD")

    # Time specification — mutually exclusive
    time_group = parser.add_mutually_exclusive_group()
    _ = time_group.add_argument(
        "--departure",
        metavar="HH:MM",
        help="Depart at HH:MM. If no time flag is given, departs now.",
    )
    _ = time_group.add_argument("--arrival", metavar="HH:MM", help="Arrive by HH:MM")
    _ = time_group.add_argument("--first", action="store_true", help="First train")
    _ = time_group.add_argument("--last", action="store_true", help="Last train")
    _ = time_group.add_argument(
        "--unspecified", action="store_true", help="No time preference"
    )

    _ = parser.add_argument(
        "--ticket",
        default="ic",
        choices=sorted(TICKET_MAP.keys()),
        help="(default: ic)",
    )
    _ = parser.add_argument(
        "--seat-preference",
        default="non_reserved",
        choices=sorted(SEAT_MAP.keys()),
        help="(default: non_reserved)",
    )
    _ = parser.add_argument(
        "--walk-speed",
        default="slightly_slow",
        choices=sorted(WALK_MAP.keys()),
        help="(default: slightly_slow)",
    )
    _ = parser.add_argument(
        "--sort-by",
        default="time",
        choices=sorted(SORT_MAP.keys()),
        help="(default: time)",
    )

    _ = parser.add_argument("--no-airline", action="store_true")
    _ = parser.add_argument("--no-shinkansen", action="store_true")
    _ = parser.add_argument("--no-express", action="store_true")
    _ = parser.add_argument("--no-highway-bus", action="store_true")
    _ = parser.add_argument("--no-local-bus", action="store_true")
    _ = parser.add_argument("--no-ferry", action="store_true")

    _ = parser.add_argument("--timeout", type=int, default=20)
    _ = parser.add_argument(
        "--show-middle",
        action="store_true",
        help="Show intermediate stations between transfer points",
    )
    _ = parser.add_argument(
        "--page", type=int, default=1, help="Result page number (3 routes per page)"
    )

    ns = parser.parse_args()

    # Resolve time_type and hour/minute from exclusive group
    arr_time = cast(str | None, ns.arrival)
    dep_time = cast(str | None, ns.departure)
    if arr_time:
        ns.time_type = "arrival"
        h_s, m_s = arr_time.split(":")
        ns.hour, ns.minute = int(h_s), int(m_s)
    elif cast(bool, ns.first):
        ns.time_type = "first_train"
        ns.hour, ns.minute = None, None
    elif cast(bool, ns.last):
        ns.time_type = "last_train"
        ns.hour, ns.minute = None, None
    elif cast(bool, ns.unspecified):
        ns.time_type = "unspecified"
        ns.hour, ns.minute = None, None
    elif dep_time:
        ns.time_type = "departure"
        h_s, m_s = dep_time.split(":")
        ns.hour, ns.minute = int(h_s), int(m_s)
    else:
        ns.time_type = "departure"
        ns.hour, ns.minute = None, None

    result = cast(_MainArgs, cast(object, ns))

    if not result.url and len(result.stations) < 2:
        parser.error("Provide --url, or at least two stations (from, to).")

    return result


def main() -> int:
    args = parse_args()
    url = args.url or build_url(args)
    if args.page > 1:
        fl = 3 * (args.page - 1) + 1
        tl = 3 * args.page
        url += f"&fl={fl}&tl={tl}"

    try:
        html = fetch_html(url, args.timeout)
        content = extract_content(html, show_middle=args.show_middle)
    except Exception as exc:  # pragma: no cover - network/runtime failures
        print(f"Error fetching route data: {exc}", file=sys.stderr)
        return 1

    print(f"URL: {_dim(url)}")
    print()
    print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
