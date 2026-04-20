#!/usr/bin/env python3
"""Fetch timetable data from Yahoo! 乗換案内."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Protocol, TypedDict, cast
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE_URL = "https://transit.yahoo.co.jp"
SUGGEST_URL = f"{BASE_URL}/api/suggest"
TIMETABLE_URL = f"{BASE_URL}/timetable"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

KIND_LABELS = {"1": "平日", "2": "土曜", "4": "日曜・祝日"}


# ── Protocols for argparse ──────────────────────────────


class _SearchArgs(Protocol):
    query: str
    station_only: bool

    timeout: int


class _LinesArgs(Protocol):
    station_code: str

    timeout: int


class _TimetableArgs(Protocol):
    station_code: str
    gid: str
    kind: str | None
    hours: str | None

    timeout: int


class _TrainArgs(Protocol):
    station_code: str
    gid: str
    train_id: str

    timeout: int


# ── TypedDicts for JSON structures ──────────────────────


class _SuggestResult(TypedDict):
    Suggest: str
    Code: str
    Id: str
    Address: str


class _SuggestResponse(TypedDict):
    Result: list[_SuggestResult]


class _RailGroup(TypedDict):
    direction: str
    groupId: str


class _RouteInfo(TypedDict):
    railName: str
    railGroup: list[_RailGroup]


class _DirectionItem(TypedDict):
    routeInfos: list[_RouteInfo]


class _DirectionDetail(TypedDict):
    stationName: str
    directionItem: _DirectionItem


class _LinesPageProps(TypedDict):
    directionDetail: _DirectionDetail


class _MasterEntry(TypedDict):
    id: str
    name: str
    info: str


class _Master(TypedDict):
    kind: list[_MasterEntry]
    destination: list[_MasterEntry]


class _MinTimeTable(TypedDict):
    minute: str
    trainId: str
    trainName: str
    kindId: str
    destinationId: str
    extraTrain: str | bool


class _HourTimeTable(TypedDict):
    hour: str
    minTimeTable: list[_MinTimeTable]


class _TimetableItem(TypedDict):
    stationName: str
    railName: str
    directionName: str
    driveDayKind: str
    hourTimeTable: list[_HourTimeTable]
    master: _Master


class _TimetablePageProps(TypedDict):
    timetableItem: _TimetableItem


class _StopStation(TypedDict):
    stationCode: str
    stationName: str
    arrivalTime: str | None
    departureTime: str | None


class _TrainTimetable(TypedDict):
    trainId: str
    displayName: str
    driveComment: str
    guideComment: str
    stopStation: list[_StopStation]


class _TrainTimetableResult(TypedDict):
    timetable: _TrainTimetable


class _TrainPageProps(TypedDict):
    timetableStationTrainResult: _TrainTimetableResult
    directionDetail: _DirectionDetail


# ── HTTP helpers ────────────────────────────────────────


def _fetch(url: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": UA})
    with urlopen(request, timeout=timeout) as resp:  # pyright: ignore[reportAny]
        charset = cast(str, resp.headers.get_content_charset()) or "utf-8"  # pyright: ignore[reportAny]
        raw = cast(bytes, resp.read())  # pyright: ignore[reportAny]
        return raw.decode(charset, errors="ignore")


def _fetch_json(url: str, timeout: int) -> object:
    result: object = json.loads(_fetch(url, timeout))  # pyright: ignore[reportAny]
    return result


class _NextDataProps(TypedDict):
    pageProps: object


class _NextData(TypedDict):
    props: _NextDataProps


def _extract_next_data(html: str) -> _NextData:
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
    )
    if not m:
        raise ValueError("Could not find __NEXT_DATA__ in page")
    return cast(_NextData, json.loads(m.group(1)))


# ── search ──────────────────────────────────────────────


def cmd_search(args: _SearchArgs) -> int:
    url = f"{SUGGEST_URL}?value={quote(args.query)}"
    print(f"URL: {url}\n")
    data = cast(_SuggestResponse, _fetch_json(url, args.timeout))

    results = data["Result"]
    if not results:
        print("No results found.")
        return 0

    stations = [r for r in results if r["Id"] == "st"]
    buses = [r for r in results if r["Id"] == "bu"]

    if stations:
        print("=== 駅 ===")
        for r in stations:
            print(f"  {r['Suggest']}  (code={r['Code']}, {r['Address']})")

    if buses and not args.station_only:
        print("=== バス停 ===")
        for r in buses[:10]:
            print(f"  {r['Suggest']}  (code={r['Code']}, {r['Address']})")
        if len(buses) > 10:
            print(f"  ... and {len(buses) - 10} more")

    return 0


# ── lines ───────────────────────────────────────────────


def cmd_lines(args: _LinesArgs) -> int:
    url = f"{TIMETABLE_URL}/{args.station_code}"
    print(f"URL: {url}\n")
    html = _fetch(url, args.timeout)
    data = _extract_next_data(html)

    page = cast(_LinesPageProps, data["props"]["pageProps"])
    station_name = page["directionDetail"]["stationName"]
    route_infos = page["directionDetail"]["directionItem"]["routeInfos"]

    print(f"=== {station_name}駅 路線一覧 ===")
    for route in route_infos:
        print(f"\n{route['railName']}:")
        for group in route["railGroup"]:
            print(f"  {group['direction']}方面  (gid={group['groupId']})")

    return 0


# ── timetable ───────────────────────────────────────────


def cmd_timetable(args: _TimetableArgs) -> int:
    url = f"{TIMETABLE_URL}/{args.station_code}/{args.gid}"
    if args.kind:
        url += f"?kind={args.kind}"
    print(f"URL: {url}\n")
    html = _fetch(url, args.timeout)
    data = _extract_next_data(html)

    page = cast(_TimetablePageProps, data["props"]["pageProps"])
    tt = page["timetableItem"]

    station_name = tt["stationName"]
    rail_name = tt["railName"]
    direction = tt["directionName"]
    kind_code = tt["driveDayKind"]

    dest_map = {d["id"]: d["name"] for d in tt["master"]["destination"]}
    kind_map = {k["id"]: k["name"] for k in tt["master"]["kind"]}

    kind_label = KIND_LABELS.get(kind_code, kind_code)
    print(f"=== {station_name}駅 {rail_name} {direction}方面 ({kind_label}) ===")
    print()

    if len(dest_map) > 1:
        dest_legend = ", ".join(
            f"{d['name']}" + (f"={d['info']}" if d["info"] else "")
            for d in tt["master"]["destination"]
        )
        print(f"行先: {dest_legend}")

    if len(kind_map) > 1:
        kind_legend = ", ".join(
            f"{k['name']}" + (f"={k['info']}" if k["info"] else "")
            for k in tt["master"]["kind"]
        )
        print(f"種別: {kind_legend}")

    if len(dest_map) > 1 or len(kind_map) > 1:
        print()

    hour_min, hour_max = 0, 99
    if args.hours:
        parts_range = args.hours.split("-")
        hour_min = int(parts_range[0])
        hour_max = int(parts_range[1]) if len(parts_range) > 1 else hour_min

    for hour_entry in tt["hourTimeTable"]:
        hour = hour_entry["hour"]
        if not (hour_min <= int(hour) <= hour_max):
            continue
        trains = hour_entry["minTimeTable"]
        if not trains:
            continue

        entries: list[str] = []
        for t in trains:
            minute = t["minute"]
            train_id = t["trainId"]
            parts: list[str] = [f"{minute}[{train_id}]"]

            kind_id = t["kindId"]
            dest_id = t["destinationId"]
            kind_info = ""
            dest_info = ""

            for k in tt["master"]["kind"]:
                if k["id"] == kind_id and k["info"]:
                    kind_info = k["info"]
            for d in tt["master"]["destination"]:
                if d["id"] == dest_id and d["info"]:
                    dest_info = d["info"]

            suffix = dest_info + kind_info
            if suffix:
                parts.append(f"({suffix})")

            if t["extraTrain"] == "true" or t["extraTrain"] is True:
                parts.append("◆")

            entries.append("".join(parts))

        print(f"  {hour:>2}時 | {' '.join(entries)}")

    return 0


def _fmt_time(raw: str | None) -> str:
    if not raw:
        return "--:--"
    raw = raw.zfill(4)
    return f"{raw[:2]}:{raw[2:]}"


# ── train ──────────────────────────────────────────────


def cmd_train(args: _TrainArgs) -> int:
    url = f"{TIMETABLE_URL}/{args.station_code}/{args.gid}/{args.train_id}"
    print(f"URL: {url}\n")
    html = _fetch(url, args.timeout)
    data = _extract_next_data(html)

    page = cast(_TrainPageProps, data["props"]["pageProps"])
    tt = page["timetableStationTrainResult"]["timetable"]
    station_name = page["directionDetail"]["stationName"]
    rail_name = page["directionDetail"]["directionItem"]["routeInfos"][0]["railName"]

    print(f"=== {station_name}駅 {rail_name} {tt['displayName']} ===")
    print()

    for stop in tt["stopStation"]:
        arr = _fmt_time(stop["arrivalTime"])
        dep = _fmt_time(stop["departureTime"])
        print(f"  {arr} → {dep}  {stop['stationName']}")

    comments = [c for c in (tt["driveComment"], tt["guideComment"]) if c]
    if comments:
        print()
        for c in comments:
            print(f"※ {c}")

    return 0


# ── CLI ─────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch timetable data from Yahoo! 乗換案内."
    )
    _ = parser.add_argument("--timeout", type=int, default=20)
    sub = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = sub.add_parser("search", help="Search for a station by name")
    _ = p_search.add_argument("query", help="Station name query (Japanese)")
    _ = p_search.add_argument(
        "--station-only",
        action="store_true",
        help="Show only train stations, not bus stops",
    )

    # lines
    p_lines = sub.add_parser("lines", help="List lines/directions for a station")
    _ = p_lines.add_argument("station_code", help="Station code from search results")

    # timetable
    p_tt = sub.add_parser("timetable", help="Show timetable for a station/line")
    _ = p_tt.add_argument("station_code", help="Station code")
    _ = p_tt.add_argument("gid", help="Line/direction group ID from 'lines' output")
    _ = p_tt.add_argument(
        "--kind",
        choices=["1", "2", "4"],
        help="Day kind: 1=weekday, 2=saturday, 4=holiday",
    )
    _ = p_tt.add_argument(
        "--hours",
        help="Filter by hour range, e.g. '5-8' or '22'",
    )

    # train
    p_train = sub.add_parser(
        "train", help="Show stop-by-stop schedule for a specific train"
    )
    _ = p_train.add_argument("station_code", help="Station code")
    _ = p_train.add_argument("gid", help="Line/direction group ID")
    _ = p_train.add_argument("train_id", help="Train ID from timetable output")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command = cast(str, args.command)
    args_obj = cast(object, args)
    try:
        if command == "search":
            return cmd_search(cast(_SearchArgs, args_obj))
        elif command == "lines":
            return cmd_lines(cast(_LinesArgs, args_obj))
        elif command == "timetable":
            return cmd_timetable(cast(_TimetableArgs, args_obj))
        elif command == "train":
            return cmd_train(cast(_TrainArgs, args_obj))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
