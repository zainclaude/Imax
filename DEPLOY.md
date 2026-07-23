# Deploying the monitor 24/7

The monitor is a single long-running Python process with two small state files.
Anywhere it runs, it needs: Python 3.9+, the repo, a filled-in `.env`, and
outbound HTTPS.

## First, the IP-address reality

AMC sits behind Cloudflare. The monitor is polite and **never** evades
challenges — it backs off when challenged. What that means for hosting:

| Where it runs | HTML fallback (no AMC key) | Official AMC API (with key) |
|---|---|---|
| Home (Pi, old laptop, Mac mini) — residential IP | usually fine | fine |
| VPS / cloud (DigitalOcean, Hetzner, AWS…) — datacenter IP | likely challenged → bot backs off | fine |

**Rule of thumb:** get a free AMC developer API key
(https://developers.amc.com/) and you can host anywhere. Without one, host at
home.

## Option A — cheap VPS (recommended, with AMC API key)

Any $4–6/mo box (Hetzner CX11, DigitalOcean basic droplet, etc.), Ubuntu/Debian:

```bash
# as root, once:
adduser --system --group amcbot
apt install -y python3-venv git
git clone https://github.com/zainclaude/imax.git /opt/imax
cd /opt/imax && git checkout claude/amc-ticket-monitor-bot-dc52dn
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env      # fill in your values (incl. AMC_API_KEY)
chown -R amcbot:amcbot /opt/imax

# run it under systemd:
cp deploy/amc-monitor.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now amc-monitor

# watch it:
journalctl -u amc-monitor -f
```

The unit auto-restarts on failure and starts on boot. Test alerts:
`sudo -u amcbot /opt/imax/.venv/bin/python -m amc_monitor.monitor --test-text`

## Option B — Raspberry Pi / spare machine at home

Same steps as Option A (a Pi running Raspberry Pi OS is Debian). Works even
without an AMC API key because your home IP looks like a normal customer.
Electricity cost of a Pi: ~$1/month.

## Option C — keep it on the Mac, but properly

If the Mac mostly stays home anyway, `launchd` runs the monitor in the
background, restarts it on crash, and starts it at login — no terminal window,
no `caffeinate` (macOS may still sleep on battery; keep it plugged in):

```bash
cp deploy/com.amcmonitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.amcmonitor.plist
# logs:
tail -f ~/Library/Logs/amc-monitor.log
```

Edit the plist first if your repo isn't at `~/imax`.

## What does NOT work well

- **Serverless / CI cron (GitHub Actions, Lambda):** state files don't persist,
  scheduling is coarse and unreliable, and the IPs are heavily challenged.
- **Free-tier web hosts (Render/Railway free plans):** they sleep idle
  processes — exactly what a monitor can't do.

## Moving state

If you later move hosts, copy `.env`, `.amc_monitor_state.json`, and
`.amc_monitor_sightings.jsonl` — the latter two carry the seeded booking
horizon, alert de-dup history, and the drop-cadence data.
