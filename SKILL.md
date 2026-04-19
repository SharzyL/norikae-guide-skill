---
name: norikae-guide
description: Plan Japan train routes and look up station timetables with Yahoo! 乗換案内, fetching real data from transit.yahoo.co.jp without MCP servers. Use when users ask for station-to-station routing in Japan, provide natural-language constraints (arrival/departure time, first/last train, cheapest/fastest/fewest transfers, transport exclusions, via stations), look up station timetables or departure schedules, or provide English/Chinese station names that must be normalized to Japanese station names before querying.
---

# Norikae Guide

## Goal

Turn a travel request into Yahoo! 乗換案内 query parameters, fetch the result page, and return useful route content. Also support station timetable lookups: searching for stations, listing available lines/directions, and displaying departure schedules.

## Workflow

1. Normalize station names.
- Convert English/Chinese station names to Japanese names used in Yahoo queries.
- Keep the exact station form users expect in Japan (for example `渋谷`, `新宿`, `東京`).
- Ask one clarification question when station name is ambiguous.

2. Extract canonical fields.
- Required: `from`, `to`
- Optional: `via` (max 3), `year`, `month`, `day`, `hour`, `minute`
- Preferences: `timeType`, `ticket`, `seatPreference`, `walkSpeed`, `sortBy`
- Transport toggles: `useAirline`, `useShinkansen`, `useExpress`, `useHighwayBus`, `useLocalBus`, `useFerry`

3. Resolve time intent.
- "arrive by" / "XX点前到" -> `timeType=arrival`
- "first train" / "始発" -> `timeType=first_train`
- "last train" / "終電" -> `timeType=last_train`
- If user gives no time, default to current local time.
- If user gives relative date words (today/tomorrow/next Friday), resolve to an absolute date before querying.

4. Build URL and fetch page content.
- Preferred command:
  `python3 scripts/fetch_norikae_routes.py --from ... --to ... --show-url`
- If URL already exists:
  `python3 scripts/fetch_norikae_routes.py --url '<url>' --show-url`
- Use `--format html` only when structured HTML fragments are needed.

5. Return concise results.
- Include URL.
- Include normalized parameters.
- Include extracted route content summary (top routes, times, transfer count, fare when available).
- If constraints conflict (for example "cheapest" and "fastest"), ask which one has higher priority.

## Intent Mapping Quick Rules

- "最便宜 / cheapest" -> `sortBy=fare`
- "最快 / fastest" -> `sortBy=time`
- "换乘最少 / fewest transfers" -> `sortBy=transfer`
- "不要新干线 / no shinkansen" -> `useShinkansen=false`
- "在来线 only / local trains only" -> `useShinkansen=false`, `useExpress=false`
- "不要巴士 / no buses" -> `useHighwayBus=false`, `useLocalBus=false`
- "现金票价" -> `ticket=cash`
- "指定席 / reserved" -> `seatPreference=reserved`
- "绿车 / Green Car" -> `seatPreference=green`

## Defaults

- `timeType=departure`
- `ticket=ic`
- `seatPreference=non_reserved`
- `walkSpeed=slightly_slow`
- `sortBy=time`
- All transport toggles default to `true`

## Output Contract

Return these sections in order:

1. `Resolved request`
- Normalized station names
- Final canonical parameters

2. `Yahoo URL`
- Full query URL

3. `Route content`
- Extracted route text (or summarized top routes)
- If live fetch fails, state failure reason and still provide URL

## Timetable Lookup Workflow

Use `scripts/fetch_timetable.py` for timetable queries. It has three subcommands:

1. **Search for a station** — find the station code by name.
   ```
   python3 scripts/fetch_timetable.py search <station-name> [--station-only]
   ```
   Returns station codes needed for subsequent commands.

2. **List lines/directions** — show available rail lines and directions at a station.
   ```
   python3 scripts/fetch_timetable.py lines <station-code>
   ```
   Returns line group IDs (gid) needed for the timetable command.

3. **Show timetable** — display the departure schedule for a specific station, line, and direction.
   ```
   python3 scripts/fetch_timetable.py timetable <station-code> <gid> [--kind 1|2|4]
   ```
   `--kind`: 1=weekday (平日), 2=saturday (土曜), 4=holiday (日曜・祝日). Defaults to today's schedule.

Typical flow: search → lines → timetable. If the user provides a station name, run `search` first to resolve the code, then `lines` to find the right gid, then `timetable` to show departures.

## Resources

- Parameter and query mapping: [references/yahoo-transit-params.md](references/yahoo-transit-params.md)
- Natural language examples: [references/natural-language-examples.md](references/natural-language-examples.md)
- Route URL builder: `scripts/build_norikae_url.py`
- Route fetch and extractor: `scripts/fetch_norikae_routes.py`
- Timetable lookup: `scripts/fetch_timetable.py`

Use `fetch_norikae_routes.py` for route search queries and `fetch_timetable.py` for timetable lookups.
