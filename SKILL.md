---
name: norikae-guide
description: Search Japan train routes and station timetables via Yahoo! 乗換案内. Use when users ask about train routing, schedules, or timetables in Japan.
---

# Norikae Guide

Search Japan train routes and look up station timetables using Yahoo! 乗換案内.
Supports English, Chinese, and Japanese input — always convert station names to Japanese before querying (e.g. Shibuya → 渋谷, 涩谷 → 渋谷).

## Route Search

```bash
python3 scripts/fetch_norikae_routes.py --from <出発駅> --to <到着駅> [options]
```

Options:
- `--via <駅>` (repeatable, max 3)
- `--year/--month/--day/--hour/--minute` — resolve relative dates to absolute values; defaults to now
- `--time-type`: `departure` (default), `arrival`, `first_train`, `last_train`, `unspecified`
- `--sort-by`: `time` (default), `fare`, `transfer`
- `--ticket`: `ic` (default), `cash`
- `--seat-preference`: `non_reserved` (default), `reserved`, `green`
- `--walk-speed`: `slightly_slow` (default), `fast`, `slightly_fast`, `slow`
- `--no-use-shinkansen`, `--no-use-express`, `--no-use-airline`, `--no-use-highway-bus`, `--no-use-local-bus`, `--no-use-ferry` — by default all transportation types are enabled; pass these flags when the user asks for a specific type

You can also fetch from an existing URL:
```bash
python3 scripts/fetch_norikae_routes.py --url '<full-yahoo-url>'
```

### Intent Mapping

| User intent | CLI flags |
| --- | --- |
| cheapest / 最便宜 | `--sort-by fare` |
| fastest / 最快 | `--sort-by time` |
| fewest transfers / 换乘最少 | `--sort-by transfer` |
| no shinkansen / 不要新干线 | `--no-use-shinkansen` |
| local trains only / 在来线 | `--no-use-shinkansen --no-use-express` |
| no buses / 不要巴士 | `--no-use-highway-bus --no-use-local-bus` |
| cash fare / 现金票价 | `--ticket cash` |
| reserved seat / 指定席 | `--seat-preference reserved` |
| Green Car / 绿车 | `--seat-preference green` |
| arrive by / XX点前到 | `--time-type arrival` |
| first train / 始発 | `--time-type first_train` |
| last train / 終電 | `--time-type last_train` |

## Timetable Lookup

Follow these steps in order:

1. **Search for the station code:**
   ```bash
   python3 scripts/fetch_timetable.py search <station-name-in-japanese> --station-only
   ```
   Use `--station-only` to exclude bus stops. Pick the matching station code from the results.

2. **List lines and directions at the station:**
   ```bash
   python3 scripts/fetch_timetable.py lines <station-code>
   ```
   This returns available lines with their `gid` (group ID). If the user specified a line, match it; otherwise ask which line/direction they want. If there is only one line, skip asking and proceed.

3. **Show the departure timetable:**
   ```bash
   python3 scripts/fetch_timetable.py timetable <station-code> <gid> [--kind 1|2|4] [--hours 5-8]
   ```
   `--kind`: `1` = weekday, `2` = saturday, `4` = holiday. Defaults to today's schedule.
   `--hours`: filter output to a range of hours (e.g. `5-8`) or a single hour (e.g. `22`).
   Each departure shows its train ID in brackets (e.g. `45[5602]`). Use this ID for step 4.

4. **Show a specific train's stop-by-stop schedule (optional):**
   ```bash
   python3 scripts/fetch_timetable.py train <station-code> <gid> <train-id>
   ```
   Use the train ID from step 3 to show all stops with arrival/departure times.

## Clarification Rules

Ask one concise clarification when:
- Station name is ambiguous (multiple matches)
- Departure station is missing and cannot be inferred
- User gives conflicting priorities (e.g. "fastest" and "cheapest") without tie-break
- Station has multiple lines and user didn't specify which one
