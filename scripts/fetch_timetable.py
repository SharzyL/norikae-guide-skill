#!/usr/bin/env python3
"""Fetch timetable data from Yahoo! 乗換案内."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
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


def _display_width(s: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(c) in ("W", "F", "A") else 1
        for c in s
    )


def _pad_right(s: str, width: int) -> str:
    return s + " " * max(0, width - _display_width(s))


# ── Protocols for argparse ──────────────────────────────


class _SearchArgs(Protocol):
    query: str
    station_only: bool

    timeout: int


class _TuiArgs(Protocol):
    query: str | None
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


# ── Data fetchers (no side effects) ─────────────────────


def _search(query: str, timeout: int) -> tuple[str, list[_SuggestResult]]:
    url = f"{SUGGEST_URL}?value={quote(query)}"
    data = cast(_SuggestResponse, _fetch_json(url, timeout))
    return url, data["Result"]


def _lines(code: str, timeout: int) -> tuple[str, _DirectionDetail]:
    url = f"{TIMETABLE_URL}/{code}"
    html = _fetch(url, timeout)
    page = cast(_LinesPageProps, _extract_next_data(html)["props"]["pageProps"])
    return url, page["directionDetail"]


def _timetable(
    code: str, gid: str, kind: str | None, timeout: int
) -> tuple[str, _TimetableItem]:
    url = f"{TIMETABLE_URL}/{code}/{gid}"
    if kind:
        url += f"?kind={kind}"
    html = _fetch(url, timeout)
    page = cast(_TimetablePageProps, _extract_next_data(html)["props"]["pageProps"])
    return url, page["timetableItem"]


def _train(
    code: str, gid: str, train_id: str, timeout: int
) -> tuple[str, _TrainPageProps]:
    url = f"{TIMETABLE_URL}/{code}/{gid}/{train_id}"
    html = _fetch(url, timeout)
    page = cast(_TrainPageProps, _extract_next_data(html)["props"]["pageProps"])
    return url, page


# ── search ──────────────────────────────────────────────


def cmd_search(args: _SearchArgs) -> int:
    url, results = _search(args.query, args.timeout)
    print(f"URL: {url}\n")

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


def _cmd_lines(station_code: str, timeout: int) -> int:
    url, detail = _lines(station_code, timeout)
    print(f"URL: {url}\n")

    print(f"=== {detail['stationName']}駅 路線一覧 ===")
    for route in detail["directionItem"]["routeInfos"]:
        print(f"\n{route['railName']}:")
        for group in route["railGroup"]:
            print(f"  {group['direction']}方面  (gid={group['groupId']})")

    return 0


# ── timetable ───────────────────────────────────────────


def _cmd_timetable(
    station_code: str,
    gid: str,
    kind: str | None,
    hours: str | None,
    timeout: int,
) -> int:
    url, tt = _timetable(station_code, gid, kind, timeout)
    print(f"URL: {url}\n")

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
    if hours:
        parts_range = hours.split("-")
        hour_min = int(parts_range[0])
        hour_max = int(parts_range[1]) if len(parts_range) > 1 else hour_min

    has_extra = False
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
                has_extra = True

            entries.append("".join(parts))

        print(f"  {hour:>2}時 | {' '.join(entries)}")

    if has_extra:
        print("\n◆：特定日または特定曜日のみ運転")

    return 0


def _fmt_time(raw: str | None) -> str:
    if not raw:
        return "--:--"
    raw = raw.zfill(4)
    return f"{raw[:2]}:{raw[2:]}"


# ── train ──────────────────────────────────────────────


def _cmd_train(station_code: str, gid: str, train_id: str, timeout: int) -> int:
    url, page = _train(station_code, gid, train_id, timeout)
    print(f"URL: {url}\n")

    tt = page["timetableStationTrainResult"]["timetable"]
    station_name = page["directionDetail"]["stationName"]
    rail_name = page["directionDetail"]["directionItem"]["routeInfos"][0]["railName"]

    print(f"=== {station_name}駅 {rail_name} {tt['displayName']} ===")
    print()

    for stop in tt["stopStation"]:
        arr = _fmt_time(stop["arrivalTime"])
        dep = _fmt_time(stop["departureTime"])
        print(f"  {arr} → {dep}  {stop['stationName']} [id={stop['stationCode']}]")

    comments = [c for c in (tt["driveComment"], tt["guideComment"]) if c]
    if comments:
        print()
        for c in comments:
            print(f"※ {c}")

    return 0


# ── TUI ─────────────────────────────────────────────────


def cmd_tui(args: _TuiArgs) -> int:
    """Interactive prompt_toolkit-based TUI. Lazily imports prompt_toolkit."""
    try:
        import asyncio  # noqa: F401
        from prompt_toolkit import Application  # pyright: ignore[reportMissingImports]
        from prompt_toolkit.buffer import Buffer  # pyright: ignore[reportMissingImports]
        from prompt_toolkit.data_structures import Point  # pyright: ignore[reportMissingImports]
        from prompt_toolkit.filters import Condition  # pyright: ignore[reportMissingImports]
        from prompt_toolkit.key_binding import KeyBindings  # pyright: ignore[reportMissingImports]
        from prompt_toolkit.layout import Layout  # pyright: ignore[reportMissingImports]
        from prompt_toolkit.layout.containers import HSplit, Window  # pyright: ignore[reportMissingImports]
        from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl  # pyright: ignore[reportMissingImports]
        from prompt_toolkit.mouse_events import MouseEventType  # pyright: ignore[reportMissingImports]
        from prompt_toolkit.styles import Style  # pyright: ignore[reportMissingImports]
    except ImportError:
        print(
            "Error: 'prompt_toolkit' is required for TUI mode.\n"
            "Install it with: pip install prompt_toolkit",
            file=sys.stderr,
        )
        return 1

    timeout = args.timeout
    initial_query = args.query or ""

    # ── State ─────────────────────────────────────────────────────

    EMPTY_HINT = "駅名を入力してください  /  Type a station name to begin"

    class S:
        screen: str = "search"
        nav_stack: list[dict[str, object]] = []
        status: str = EMPTY_HINT

        # search
        search_results: list[_SuggestResult] = []
        search_idx: int = 0
        last_query: str = ""

        # lines
        lines_station_name: str = ""
        lines_station_code: str = ""
        lines_items: list[dict[str, str]] = []
        lines_idx: int = 0

        # timetable
        tt_station_name: str = ""
        tt_code: str = ""
        tt_gid: str = ""
        tt_kind: str | None = None
        tt_hours: list[_HourTimeTable] = []
        tt_dest_map: dict[str, _MasterEntry] = {}
        tt_kind_map: dict[str, _MasterEntry] = {}
        tt_header: str = ""
        tt_h: int = 0
        tt_t: int = 0

        # train
        train_code: str = ""
        train_gid: str = ""
        train_train_id: str = ""
        train_here_code: str = ""
        train_header: str = ""
        train_stops: list[_StopStation] = []
        train_comments: list[str] = []
        train_idx: int = 0

    # ── Forward declarations ──────────────────────────────────────

    app: "Application"  # set below
    suppress_change = [False]
    debounce_task: list[object] = [None]
    # Bumped on every push/back/set_kind so in-flight loads can detect
    # they're stale and discard their results.
    load_gen = [0]

    # ── Buffer + debounce ─────────────────────────────────────────

    def schedule_search(query: str) -> None:
        if debounce_task[0] is not None:
            try:
                debounce_task[0].cancel()  # pyright: ignore[reportAttributeAccessIssue]
            except Exception:
                pass
            debounce_task[0] = None

        async def run() -> None:
            try:
                await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                return
            await do_search(query)

        debounce_task[0] = app.create_background_task(run())

    def on_search_text_changed(buf: "Buffer") -> None:
        if suppress_change[0]:
            return
        q = buf.text.strip()
        if not q:
            if debounce_task[0] is not None:
                try:
                    debounce_task[0].cancel()  # pyright: ignore[reportAttributeAccessIssue]
                except Exception:
                    pass
                debounce_task[0] = None
            S.search_results = []
            S.search_idx = 0
            S.last_query = ""
            S.status = EMPTY_HINT
            app.invalidate()
            return
        schedule_search(q)

    search_buffer = Buffer(on_text_changed=on_search_text_changed, multiline=False)

    # ── Async fetchers ────────────────────────────────────────────

    async def _run_blocking(fn, *fargs):  # pyright: ignore[reportMissingParameterType]
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, fn, *fargs)

    async def do_search(query: str) -> None:
        S.last_query = query
        S.status = f"Searching '{query}'…"
        app.invalidate()
        try:
            _, raw = await _run_blocking(_search, query, timeout)
            if query != S.last_query:
                return
            stations = [r for r in raw if r["Id"] == "st"]
            S.search_results = stations
            S.search_idx = 0
            S.status = (
                f"{len(stations)} 件  —  ↑/↓ to highlight, Enter to open"
                if stations
                else "候補なし"
            )
        except Exception as e:
            S.status = f"Error: {e}"
        app.invalidate()

    async def do_load_lines() -> None:
        my_gen = load_gen[0]
        S.status = "Loading…"
        app.invalidate()
        try:
            _, detail = await _run_blocking(_lines, S.lines_station_code, timeout)
            if my_gen != load_gen[0]:
                return
            items: list[dict[str, str]] = []
            for route in detail["directionItem"]["routeInfos"]:
                for g in route["railGroup"]:
                    items.append(
                        {
                            "rail": route["railName"],
                            "direction": g["direction"],
                            "gid": g["groupId"],
                        }
                    )
            S.lines_items = items
            S.lines_idx = 0
            S.status = (
                f"{len(items)} lines — Enter to view timetable, Esc to go back"
            )
        except Exception as e:
            if my_gen != load_gen[0]:
                return
            S.status = f"Error: {e}"
        app.invalidate()

    async def do_load_timetable() -> None:
        my_gen = load_gen[0]
        S.status = "Loading…"
        app.invalidate()
        try:
            _, tt = await _run_blocking(
                _timetable, S.tt_code, S.tt_gid, S.tt_kind, timeout
            )
            if my_gen != load_gen[0]:
                return
            kind_label = KIND_LABELS.get(tt["driveDayKind"], tt["driveDayKind"])
            S.tt_header = (
                f"{tt['stationName']}駅  {tt['railName']}  "
                f"{tt['directionName']}方面  ({kind_label})"
            )
            S.tt_dest_map = {d["id"]: d for d in tt["master"]["destination"]}
            S.tt_kind_map = {k["id"]: k for k in tt["master"]["kind"]}
            S.tt_hours = [h for h in tt["hourTimeTable"] if h["minTimeTable"]]
            S.tt_h = 0
            S.tt_t = 0
            update_tt_status_info()
        except Exception as e:
            if my_gen != load_gen[0]:
                return
            S.status = f"Error: {e}"
        app.invalidate()

    async def do_load_train() -> None:
        my_gen = load_gen[0]
        S.status = "Loading…"
        app.invalidate()
        try:
            _, page = await _run_blocking(
                _train, S.train_code, S.train_gid, S.train_train_id, timeout
            )
            if my_gen != load_gen[0]:
                return
            tt = page["timetableStationTrainResult"]["timetable"]
            station_name = page["directionDetail"]["stationName"]
            rail_name = page["directionDetail"]["directionItem"]["routeInfos"][0][
                "railName"
            ]
            S.train_header = f"{station_name}駅  {rail_name}  {tt['displayName']}"
            S.train_stops = list(tt["stopStation"])
            S.train_comments = [
                c for c in (tt["driveComment"], tt["guideComment"]) if c
            ]
            here = next(
                (
                    i
                    for i, s in enumerate(S.train_stops)
                    if s["stationCode"] == S.train_here_code
                ),
                0,
            )
            S.train_idx = here
            S.status = (
                f"{len(S.train_stops)} stops — Enter on a station to view its lines"
            )
        except Exception as e:
            if my_gen != load_gen[0]:
                return
            S.status = f"Error: {e}"
        app.invalidate()

    # ── Render functions ──────────────────────────────────────────

    def _term_cols() -> int:
        try:
            return app.output.get_size().columns
        except Exception:
            return 80

    def _pad_to(text: str, cols: int) -> str:
        pad = cols - _display_width(text)
        if pad > 0:
            text = text + " " * pad
        return text

    def get_title():
        if S.screen == "search":
            return [("class:title", " 駅名検索 / Station Search ")]
        if S.screen == "lines":
            return [("class:title", f" {S.lines_station_name}駅  路線一覧 ")]
        if S.screen == "timetable":
            return [("class:title", f" {S.tt_header or 'Loading…'} ")]
        if S.screen == "train":
            return [("class:title", f" {S.train_header or '列車詳細'} ")]
        return [("", "")]

    def get_status():
        return [("class:status", f" {S.status} ")]

    def get_footer():
        text = {
            "search": " Esc:Quit  ↑/↓:Navigate  Enter:Open ",
            "lines": " Esc:Back  ↑/↓ or j/k:Navigate  Enter:Open  g/G:Top/Bottom ",
            "timetable": (
                " Esc:Back  hjkl/←↑→↓:Move  Enter:Detail  "
                "1/2/4/0:Kind  g/G:Top/Bottom "
            ),
            "train": " Esc:Back  ↑/↓ or j/k:Navigate  Enter:View Lines ",
        }.get(S.screen, "")
        return [("class:footer", text)]

    def _click_open_search(idx: int):
        def handler(mouse_event):
            if mouse_event.event_type != MouseEventType.MOUSE_UP:
                return NotImplemented
            if 0 <= idx < len(S.search_results):
                S.search_idx = idx
                r = S.search_results[idx]
                push_lines(r["Suggest"], r["Code"])
        return handler

    def get_search_results():
        if not S.search_results:
            return [("", "")]
        cols = _term_cols()
        out: list[tuple] = []
        for i, r in enumerate(S.search_results):
            label = _pad_to(f" {r['Suggest']}    {r['Address']}", cols) + "\n"
            style = "class:selected" if i == S.search_idx else ""
            out.append((style, label, _click_open_search(i)))
        return out

    def get_search_cursor():
        return Point(x=0, y=S.search_idx)

    def _click_open_line(idx: int):
        def handler(mouse_event):
            if mouse_event.event_type != MouseEventType.MOUSE_UP:
                return NotImplemented
            if 0 <= idx < len(S.lines_items):
                S.lines_idx = idx
                push_timetable(S.lines_items[idx]["gid"])
        return handler

    def get_lines_body():
        if not S.lines_items:
            return [("", "")]
        max_rail_w = max(_display_width(it["rail"]) for it in S.lines_items)
        cols = _term_cols()
        out: list[tuple] = []
        prev_rail = None
        for i, it in enumerate(S.lines_items):
            if it["rail"] == prev_rail:
                rail = " " * max_rail_w
            else:
                rail = _pad_right(it["rail"], max_rail_w)
            prev_rail = it["rail"]
            label = _pad_to(f" {rail}    {it['direction']}方面", cols) + "\n"
            style = "class:selected" if i == S.lines_idx else ""
            out.append((style, label, _click_open_line(i)))
        return out

    def get_lines_cursor():
        return Point(x=0, y=S.lines_idx)

    def update_tt_status_info() -> None:
        if not S.tt_hours:
            return
        h = S.tt_hours[S.tt_h]
        t = h["minTimeTable"][S.tt_t]
        hour_label = f"{int(h['hour']):>2}時"
        time_str = f"{hour_label} {t['minute'].zfill(2)}分"
        parts: list[str] = []
        knd = S.tt_kind_map.get(t["kindId"])
        if knd and knd.get("name"):
            parts.append(knd["name"])
        dest = S.tt_dest_map.get(t["destinationId"])
        if dest and dest.get("name"):
            parts.append(f"{dest['name']} 行")
        if t["extraTrain"] in (True, "true"):
            parts.append("◆ 特定日/特定曜日のみ運転")
        info = "   ".join(parts)
        S.status = f"{time_str}    {info}" if info else time_str

    def _click_open_train_cell(h_idx: int, t_idx: int):
        def handler(mouse_event):
            if mouse_event.event_type != MouseEventType.MOUSE_UP:
                return NotImplemented
            if h_idx >= len(S.tt_hours):
                return
            trains = S.tt_hours[h_idx]["minTimeTable"]
            if t_idx >= len(trains):
                return
            S.tt_h = h_idx
            S.tt_t = t_idx
            update_tt_status_info()
            push_train(trains[t_idx]["trainId"])
        return handler

    def get_timetable_body():
        if not S.tt_hours:
            return [("", "")]
        out: list[tuple] = []
        for h_idx, h in enumerate(S.tt_hours):
            hour_label = f"{int(h['hour']):>2}時"
            out.append(("class:hour", hour_label))
            out.append(("", "  "))
            for t_idx, t in enumerate(h["minTimeTable"]):
                is_sel = h_idx == S.tt_h and t_idx == S.tt_t
                rev = "reverse " if is_sel else ""
                click = _click_open_train_cell(h_idx, t_idx)
                minute = t["minute"].zfill(2)
                out.append((rev, minute, click))
                dest = S.tt_dest_map.get(t["destinationId"])
                if dest and dest.get("info"):
                    out.append((rev + "class:dest", dest["info"][:1], click))
                knd = S.tt_kind_map.get(t["kindId"])
                if knd and knd.get("info"):
                    out.append((rev + "class:kind", knd["info"][:1], click))
                if t["extraTrain"] in (True, "true"):
                    out.append((rev + "class:extra", "◆", click))
                out.append(("", "  "))
            out.append(("", "\n"))
        return out

    def get_timetable_cursor():
        return Point(x=0, y=S.tt_h)

    def _click_open_stop(idx: int):
        def handler(mouse_event):
            if mouse_event.event_type != MouseEventType.MOUSE_UP:
                return NotImplemented
            if 0 <= idx < len(S.train_stops):
                stop = S.train_stops[idx]
                code = stop["stationCode"]
                if code:
                    S.train_idx = idx
                    push_lines(stop["stationName"], code)
        return handler

    def get_train_body():
        if not S.train_stops:
            return [("", "")]
        cols = _term_cols()
        out: list[tuple] = []
        here_idx = next(
            (
                i
                for i, s in enumerate(S.train_stops)
                if s["stationCode"] == S.train_here_code
            ),
            -1,
        )
        for i, stop in enumerate(S.train_stops):
            arr = _fmt_time(stop["arrivalTime"])
            dep = _fmt_time(stop["departureTime"])
            name = stop["stationName"]
            is_here = i == here_idx
            marker = "▶ " if is_here else "  "
            line = _pad_to(f" {arr}  {dep}  {marker}{name}", cols) + "\n"
            click = _click_open_stop(i)
            if i == S.train_idx:
                out.append(("class:selected", line, click))
            elif is_here:
                out.append(("class:here", line, click))
            else:
                out.append(("", line, click))
        if S.train_comments:
            out.append(("", "\n"))
            for c in S.train_comments:
                out.append(("class:comment", f" ※ {c}\n"))
        return out

    def get_train_cursor():
        return Point(x=0, y=S.train_idx)

    # ── Navigation ────────────────────────────────────────────────

    def snapshot() -> dict[str, object]:
        return {
            "screen": S.screen,
            "search_results": list(S.search_results),
            "search_idx": S.search_idx,
            "search_text": search_buffer.text,
            "last_query": S.last_query,
            "lines_station_name": S.lines_station_name,
            "lines_station_code": S.lines_station_code,
            "lines_items": list(S.lines_items),
            "lines_idx": S.lines_idx,
            "tt_station_name": S.tt_station_name,
            "tt_code": S.tt_code,
            "tt_gid": S.tt_gid,
            "tt_kind": S.tt_kind,
            "tt_hours": list(S.tt_hours),
            "tt_dest_map": dict(S.tt_dest_map),
            "tt_kind_map": dict(S.tt_kind_map),
            "tt_header": S.tt_header,
            "tt_h": S.tt_h,
            "tt_t": S.tt_t,
            "train_code": S.train_code,
            "train_gid": S.train_gid,
            "train_train_id": S.train_train_id,
            "train_here_code": S.train_here_code,
            "train_header": S.train_header,
            "train_stops": list(S.train_stops),
            "train_comments": list(S.train_comments),
            "train_idx": S.train_idx,
            "status": S.status,
        }

    def restore(snap: dict[str, object]) -> None:
        for k, v in snap.items():
            if k == "search_text":
                continue
            setattr(S, k, v)
        if S.screen == "search":
            suppress_change[0] = True
            search_buffer.text = cast(str, snap.get("search_text", ""))
            suppress_change[0] = False
        app.layout = build_layout()

    def push_lines(station_name: str, code: str) -> None:
        load_gen[0] += 1
        S.nav_stack.append(snapshot())
        S.screen = "lines"
        S.lines_station_name = station_name
        S.lines_station_code = code
        S.lines_items = []
        S.lines_idx = 0
        S.status = "Loading…"
        app.layout = build_layout()
        _ = app.create_background_task(do_load_lines())
        app.invalidate()

    def push_timetable(gid: str) -> None:
        load_gen[0] += 1
        S.nav_stack.append(snapshot())
        S.screen = "timetable"
        S.tt_station_name = S.lines_station_name
        S.tt_code = S.lines_station_code
        S.tt_gid = gid
        S.tt_kind = None
        S.tt_hours = []
        S.tt_h = 0
        S.tt_t = 0
        S.tt_header = ""
        S.status = "Loading…"
        app.layout = build_layout()
        _ = app.create_background_task(do_load_timetable())
        app.invalidate()

    def push_train(train_id: str) -> None:
        load_gen[0] += 1
        S.nav_stack.append(snapshot())
        S.screen = "train"
        S.train_code = S.tt_code
        S.train_gid = S.tt_gid
        S.train_train_id = train_id
        S.train_here_code = S.tt_code
        S.train_stops = []
        S.train_comments = []
        S.train_idx = 0
        S.train_header = ""
        S.status = "Loading…"
        app.layout = build_layout()
        _ = app.create_background_task(do_load_train())
        app.invalidate()

    def go_back() -> None:
        if not S.nav_stack:
            app.exit()
            return
        load_gen[0] += 1
        snap = S.nav_stack.pop()
        restore(snap)
        app.invalidate()

    def set_kind(kind: str | None) -> None:
        if S.tt_kind == kind:
            return
        load_gen[0] += 1
        S.tt_kind = kind
        S.status = "Loading…"
        _ = app.create_background_task(do_load_timetable())
        app.invalidate()

    # ── Key bindings ──────────────────────────────────────────────

    is_search = Condition(lambda: S.screen == "search")
    is_lines = Condition(lambda: S.screen == "lines")
    is_timetable = Condition(lambda: S.screen == "timetable")
    is_train = Condition(lambda: S.screen == "train")
    is_not_search = Condition(lambda: S.screen != "search")

    # Bindings attached to the search input (highest priority for the input):
    search_kb = KeyBindings()

    @search_kb.add("escape")
    @search_kb.add("c-c")
    def _(event):
        event.app.exit()

    @search_kb.add("down")
    @search_kb.add("c-n")
    def _(event):
        if S.search_results:
            S.search_idx = min(len(S.search_results) - 1, S.search_idx + 1)
            event.app.invalidate()

    @search_kb.add("up")
    @search_kb.add("c-p")
    def _(event):
        if S.search_results:
            S.search_idx = max(0, S.search_idx - 1)
            event.app.invalidate()

    @search_kb.add("enter")
    def _(event):
        del event
        if not S.search_results:
            return
        r = S.search_results[S.search_idx]
        push_lines(r["Suggest"], r["Code"])

    @search_kb.add("pageup")
    def _(event):
        if S.search_results:
            S.search_idx = 0
            event.app.invalidate()

    @search_kb.add("pagedown")
    def _(event):
        if S.search_results:
            S.search_idx = len(S.search_results) - 1
            event.app.invalidate()

    # Global bindings (apply to non-search screens):
    kb = KeyBindings()

    @kb.add("escape", filter=is_not_search)
    @kb.add("q", filter=is_not_search)
    def _(event):
        del event
        go_back()

    # Lines
    @kb.add("down", filter=is_lines)
    @kb.add("j", filter=is_lines)
    def _(event):
        if S.lines_items:
            S.lines_idx = min(len(S.lines_items) - 1, S.lines_idx + 1)
            event.app.invalidate()

    @kb.add("up", filter=is_lines)
    @kb.add("k", filter=is_lines)
    def _(event):
        if S.lines_items:
            S.lines_idx = max(0, S.lines_idx - 1)
            event.app.invalidate()

    @kb.add("g", filter=is_lines)
    def _(event):
        S.lines_idx = 0
        event.app.invalidate()

    @kb.add("G", filter=is_lines)
    def _(event):
        if S.lines_items:
            S.lines_idx = len(S.lines_items) - 1
            event.app.invalidate()

    @kb.add("enter", filter=is_lines)
    def _(event):
        del event
        if not S.lines_items:
            return
        it = S.lines_items[S.lines_idx]
        push_timetable(it["gid"])

    # Timetable
    def tt_move(dx: int, dy: int) -> None:
        if not S.tt_hours:
            return
        if dy != 0:
            S.tt_h = max(0, min(len(S.tt_hours) - 1, S.tt_h + dy))
            n = len(S.tt_hours[S.tt_h]["minTimeTable"])
            S.tt_t = max(0, min(S.tt_t, n - 1))
        if dx != 0:
            n = len(S.tt_hours[S.tt_h]["minTimeTable"])
            new_t = S.tt_t + dx
            if new_t < 0 and S.tt_h > 0:
                S.tt_h -= 1
                S.tt_t = max(0, len(S.tt_hours[S.tt_h]["minTimeTable"]) - 1)
            elif new_t >= n and S.tt_h < len(S.tt_hours) - 1:
                S.tt_h += 1
                S.tt_t = 0
            else:
                S.tt_t = max(0, min(n - 1, new_t))
        update_tt_status_info()

    @kb.add("left", filter=is_timetable)
    @kb.add("h", filter=is_timetable)
    def _(event):
        tt_move(-1, 0)
        event.app.invalidate()

    @kb.add("right", filter=is_timetable)
    @kb.add("l", filter=is_timetable)
    def _(event):
        tt_move(1, 0)
        event.app.invalidate()

    @kb.add("up", filter=is_timetable)
    @kb.add("k", filter=is_timetable)
    def _(event):
        tt_move(0, -1)
        event.app.invalidate()

    @kb.add("down", filter=is_timetable)
    @kb.add("j", filter=is_timetable)
    def _(event):
        tt_move(0, 1)
        event.app.invalidate()

    @kb.add("g", filter=is_timetable)
    def _(event):
        if S.tt_hours:
            S.tt_h = 0
            n = len(S.tt_hours[0]["minTimeTable"])
            S.tt_t = min(S.tt_t, n - 1)
            update_tt_status_info()
            event.app.invalidate()

    @kb.add("G", filter=is_timetable)
    def _(event):
        if S.tt_hours:
            S.tt_h = len(S.tt_hours) - 1
            n = len(S.tt_hours[S.tt_h]["minTimeTable"])
            S.tt_t = min(S.tt_t, n - 1)
            update_tt_status_info()
            event.app.invalidate()

    @kb.add("1", filter=is_timetable)
    def _(event):
        del event
        set_kind("1")

    @kb.add("2", filter=is_timetable)
    def _(event):
        del event
        set_kind("2")

    @kb.add("4", filter=is_timetable)
    def _(event):
        del event
        set_kind("4")

    @kb.add("0", filter=is_timetable)
    def _(event):
        del event
        set_kind(None)

    @kb.add("enter", filter=is_timetable)
    def _(event):
        del event
        if not S.tt_hours:
            return
        t = S.tt_hours[S.tt_h]["minTimeTable"][S.tt_t]
        push_train(t["trainId"])

    # Train
    @kb.add("down", filter=is_train)
    @kb.add("j", filter=is_train)
    def _(event):
        if S.train_stops:
            S.train_idx = min(len(S.train_stops) - 1, S.train_idx + 1)
            event.app.invalidate()

    @kb.add("up", filter=is_train)
    @kb.add("k", filter=is_train)
    def _(event):
        if S.train_stops:
            S.train_idx = max(0, S.train_idx - 1)
            event.app.invalidate()

    @kb.add("g", filter=is_train)
    def _(event):
        S.train_idx = 0
        event.app.invalidate()

    @kb.add("G", filter=is_train)
    def _(event):
        if S.train_stops:
            S.train_idx = len(S.train_stops) - 1
            event.app.invalidate()

    @kb.add("enter", filter=is_train)
    def _(event):
        del event
        if not S.train_stops:
            return
        stop = S.train_stops[S.train_idx]
        if stop["stationCode"]:
            push_lines(stop["stationName"], stop["stationCode"])

    # ── Layout ────────────────────────────────────────────────────

    def build_layout():
        title_w = Window(FormattedTextControl(get_title), height=1)
        status_w = Window(FormattedTextControl(get_status), height=1)
        footer_w = Window(FormattedTextControl(get_footer), height=1)

        if S.screen == "search":
            input_w = Window(
                BufferControl(buffer=search_buffer, key_bindings=search_kb),
                height=1,
                style="class:input",
            )
            results_w = Window(
                FormattedTextControl(
                    text=get_search_results,
                    get_cursor_position=get_search_cursor,
                    show_cursor=False,
                ),
            )
            layout = Layout(HSplit([title_w, input_w, status_w, results_w, footer_w]))
            layout.focus(input_w)
            return layout

        if S.screen == "lines":
            body = Window(
                FormattedTextControl(
                    text=get_lines_body,
                    get_cursor_position=get_lines_cursor,
                    focusable=True,
                    show_cursor=False,
                ),
            )
            layout = Layout(HSplit([title_w, status_w, body, footer_w]))
            layout.focus(body)
            return layout

        if S.screen == "timetable":
            body = Window(
                FormattedTextControl(
                    text=get_timetable_body,
                    get_cursor_position=get_timetable_cursor,
                    focusable=True,
                    show_cursor=False,
                ),
                wrap_lines=True,
            )
            layout = Layout(HSplit([title_w, status_w, body, footer_w]))
            layout.focus(body)
            return layout

        if S.screen == "train":
            body = Window(
                FormattedTextControl(
                    text=get_train_body,
                    get_cursor_position=get_train_cursor,
                    focusable=True,
                    show_cursor=False,
                ),
            )
            layout = Layout(HSplit([title_w, status_w, body, footer_w]))
            layout.focus(body)
            return layout

        return Layout(Window(FormattedTextControl("")))

    # ── Style ─────────────────────────────────────────────────────

    style = Style.from_dict(
        {
            "title": "reverse bold",
            "status": "fg:#888888",
            "footer": "reverse",
            "input": "bold",
            "selected": "noreverse bg:#005f87 fg:#ffffff bold",
            "hour": "fg:cyan bold",
            "dest": "fg:green",
            "kind": "fg:yellow",
            "extra": "fg:red",
            "here": "fg:yellow bold",
            "comment": "fg:#ffaa00",
        }
    )

    # ── App ───────────────────────────────────────────────────────

    app = Application(
        layout=build_layout(),
        key_bindings=kb,
        full_screen=True,
        mouse_support=True,
        style=style,
    )

    def pre_run() -> None:
        if initial_query:
            suppress_change[0] = True
            search_buffer.text = initial_query
            suppress_change[0] = False
            _ = app.create_background_task(do_search(initial_query))

    try:
        app.run(pre_run=pre_run)
    except KeyboardInterrupt:
        pass
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

    # timetable: 1 arg = lines, 2 args = timetable, 3 args = train
    p_tt = sub.add_parser(
        "timetable",
        help=(
            "station_code [gid [train_id]]: "
            "1 arg = list lines, 2 args = show timetable, 3 args = show train"
        ),
    )
    _ = p_tt.add_argument(
        "args",
        nargs="+",
        help="station_code [gid [train_id]]",
    )
    _ = p_tt.add_argument(
        "--kind",
        choices=["1", "2", "4"],
        help="Day kind: 1=weekday, 2=saturday, 4=holiday (timetable mode only)",
    )
    _ = p_tt.add_argument(
        "--hours",
        help="Filter by hour range, e.g. '5-8' or '22' (timetable mode only)",
    )

    # tui
    p_tui = sub.add_parser(
        "tui",
        help="Interactive TUI (requires `pip install prompt_toolkit`)",
    )
    _ = p_tui.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Optional initial station search query (Japanese)",
    )

    return parser.parse_args()


def main() -> int:
    ns = parse_args()
    command = cast(str, ns.command)
    timeout = cast(int, ns.timeout)
    try:
        if command == "search":
            return cmd_search(cast(_SearchArgs, cast(object, ns)))
        elif command == "tui":
            return cmd_tui(cast(_TuiArgs, cast(object, ns)))
        elif command == "timetable":
            tt_args = cast(list[str], ns.args)
            if len(tt_args) == 1:
                return _cmd_lines(tt_args[0], timeout)
            elif len(tt_args) == 2:
                return _cmd_timetable(
                    tt_args[0],
                    tt_args[1],
                    cast(str | None, ns.kind),
                    cast(str | None, ns.hours),
                    timeout,
                )
            elif len(tt_args) >= 3:
                return _cmd_train(tt_args[0], tt_args[1], tt_args[2], timeout)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
