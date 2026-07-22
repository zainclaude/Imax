# AMC 70mm Odyssey Monitor (Lincoln Square)

A **polite availability notifier** for the 70mm IMAX presentation of *The Odyssey*
at **AMC Lincoln Square 13** in NYC.

It does **one** thing: watches for the showtimes to appear (or for adjacent seat
pairs to open up), and then sends a text to you and your wife with a direct link
so **you** can log in and book. It is a heads-up tool, not an auto-buyer.

## What this is NOT

This project deliberately does **not**:

- bypass, solve, or evade Cloudflare / bot-mitigation challenges,
- spoof or rotate browser fingerprints to look like many users,
- automate checkout or purchasing,
- hammer AMC with high-frequency requests.

Automating purchases against AMC violates their Terms of Service and defeats the
anti-bot layer on purpose. This tool stays on the right side of that line: it
polls a public endpoint on a **human cadence**, backs off politely when asked
(`429`/`503`), identifies itself honestly, and just pings you. You remain the
human who logs in and checks out.

If AMC blocks polite automated reads, the correct move is to use their
**official developer API** (https://developers.amc.com/) rather than to evade the
block. The client below is built to prefer that API when a key is present.

## Alert modes

Pick what you want to be texted about with `ALERT_MODE` (one or more, comma-separated):

| Mode | Texts you when… | Good for |
|---|---|---|
| `new_date` *(default)* | a **brand-new bookable date** appears — the booking horizon extends (e.g. Aug 16 was the furthest-out date, then Aug 17 shows up) | catching a whole new day / fresh batch of seats dropping — usually the signal that matters most |
| `adjacent_pair` | a showtime has **two open seats next to each other** | grabbing two seats together on a day that's already on sale |
| `any_showtime` | **any** new showtime slot appears | maximum awareness, more noise |

Example — get both: `ALERT_MODE=new_date,adjacent_pair`

**How `new_date` avoids spamming you on startup:** the first poll silently records
the *current* horizon (every date already for sale). You only get a text when a
date appears that wasn't there when the monitor started watching. Dates are
computed in **Eastern time**, so an overnight 2 a.m. show lands on the correct
calendar day.

## How it works

1. Every few minutes, query AMC for *Odyssey* showtimes at Lincoln Square.
2. Stamp the first-sighting of every slot (for cadence learning, below).
3. Fire whichever alerts your `ALERT_MODE` asks for (new date / adjacent pair /
   any showtime), each de-duplicated so you're texted once per event.
4. Send a group text with a one-tap deep link, then stay quiet otherwise.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # fill in the values
python -m amc_monitor.monitor
```

### Configuration (`.env`)

| Variable | Meaning |
|---|---|
| `AMC_API_KEY` | Optional. AMC developer API key. Strongly preferred over HTML scraping. |
| `AMC_THEATRE_ID` | AMC theatre id for Lincoln Square 13 (see note below). |
| `MOVIE_QUERY` | Title match, default `Odyssey`. |
| `FORMAT_MATCH` | Format substring to require, default `70`. Matches "70mm" / "IMAX 70mm". |
| `POLL_SECONDS` | Base poll interval. Default `180` (3 min). Please keep this humane. |
| `ALERT_MODE` | What to text you about: `new_date` (default), `adjacent_pair`, `any_showtime`. Comma-separate to combine. See **Alert modes** above. |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | Twilio credentials. |
| `TWILIO_FROM` | Your Twilio sending number. |
| `ALERT_NUMBERS` | Comma-separated recipient numbers (you + your wife). |
| `TWILIO_MESSAGING_SERVICE_SID` | Optional. Set this to use a Group MMS thread. |

> **Theatre id:** Lincoln Square's AMC id is stable but AMC occasionally renumbers.
> With an `AMC_API_KEY` set, run `python -m amc_monitor.find_theatre "Lincoln Square"`
> to confirm the current id.

## Group text

Two options, both handled by `notifier.py`:

- **Simple (default):** the same SMS is sent to each number in `ALERT_NUMBERS`.
  Reliable everywhere; each person gets a 1:1 text.
- **True group thread:** set `TWILIO_MESSAGING_SERVICE_SID` to a Twilio
  Conversations / Group MMS service and both recipients share one MMS thread.

## Learning the drop cadence

AMC doesn't publish when it adds new Odyssey 70mm showtimes, and there's no fixed
time — but there *is* a per-theatre pattern (often overnight ET, midweek). The
monitor learns it for you: every time a slot first appears, it stamps the moment
to `.amc_monitor_sightings.jsonl`. After a few days, run:

```bash
python -m amc_monitor.patterns
```

to see the drops bucketed by weekday and hour in Eastern time, e.g.:

```
By weekday:
  Tue    4  ████████████████████████
  Wed    5  ██████████████████████████████
By hour (ET):
  02:00    5  ██████████████████████████████
  03:00    2  ████████████

Likely drop window: around Wed, hours 02:00, 03:00, 01:00 ET.
```

Now you know when to actually be ready — and you can keep the poll rate polite the
rest of the week instead of hammering AMC around the clock.

## Running it for real

- Locally with `python -m amc_monitor.monitor` (foreground) or under `systemd` /
  `launchd`.
- Or as a cron / scheduled job that runs one poll per invocation
  (`python -m amc_monitor.monitor --once`).
