"""Fortress -> Beeminder daily check. Python 3.9+, standard library only.

Run it hourly. It posts a "1" to one Beeminder goal at most once a day, and only when
every rule below passes:

  devices     every expected device checked in within max_hours (Fortress Core's status
              page on this PC). If Core is off, devices can't check in, so this fails.
  deliveries  at most max_per_week food or grocery delivery orders, Monday to Sunday,
              from Pocket Ledger's synced bank transactions on this PC. Charges from the
              same service on the same day are one order. Stale data (Pocket Ledger not
              synced within max_sync_age_hours) fails.
  workouts    last week, every training day in Block Trainer was fully logged
              (days_per_week, taken from the block). Checked on the first day of each
              new week; on other days it reports progress and passes.
  weight      a bodyweight entry dated today in Block Trainer. The act of logging is what
              counts, not the number.
  steps       yesterday's step total reached min (10,000). Fortress Agent reads daily
              totals from Android's Health Connect, where Gadgetbridge puts the watch's
              steps. Yesterday only counts once the phone has read it after midnight.

Block Trainer's numbers reach this PC through Fortress: Block Trainer hands a summary to
Fortress Agent on the phone, which passes it to Core at every check-in. Step totals take
the same road, as the "steps" report.

A failed rule only withholds that day's point. How many missed days the goal allows
before it derails is set on the goal itself in Beeminder.

Usage:   python beeminder_check.py --config C:\\ProgramData\\Fortress\\beeminder\\config.json
         python beeminder_check.py --config ... --dry-run      (checks, posts nothing)
The log (beeminder-log.txt) and state (beeminder-state.json) live next to the config.
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = "http://127.0.0.1:47800/api/v1"
LOG_MAX_BYTES = 1_000_000


# ---- helpers ----------------------------------------------------------------------------

class Log:
    def __init__(self, path):
        self.path = path

    def __call__(self, msg):
        line = f"{datetime.now():%Y-%m-%d %H:%M} {msg}"
        print(line)
        try:
            if self.path.exists() and self.path.stat().st_size > LOG_MAX_BYTES:
                keep = self.path.read_text(encoding="utf-8").splitlines()[-2000:]
                self.path.write_text("\n".join(keep) + "\n", encoding="utf-8")
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def parse_utc(text):
    return datetime.fromisoformat(str(text).replace("Z", "+00:00"))


def norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def fetch_json(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.load(r)
    except (OSError, ValueError):
        return None


def latest_report(reports, source):
    """The newest report from [source] across all devices, as the app sent it."""
    best = None
    for by_source in (reports or {}).values():
        rep = ((by_source or {}).get(source) or {}).get("report") or {}
        if rep and (best is None or str(rep.get("at", "")) > str(best.get("at", ""))):
            best = rep
    return (best or {}).get("data")


def monday_of(day):
    return day - timedelta(days=day.weekday())


# ---- rules: each returns (passed, summary, detail) --------------------------------------

def rule_devices(cfg, now, status):
    if status is None:
        return False, "Fortress Core isn't running", "its status page didn't answer"
    if not status.get("set_up"):
        return False, "Fortress Core isn't set up", ""
    by_id = {d["id"]: d for d in status.get("devices", [])}
    bad, ok = [], []
    for dev in cfg["devices"]:
        d = by_id.get(dev)
        if d is None:
            bad.append(f"{dev} not in Fortress")
        elif not d.get("enrolled"):
            bad.append(f"{dev} not enrolled")
        elif not d.get("last_seen"):
            bad.append(f"{dev} never checked in")
        else:
            hours = (now - parse_utc(d["last_seen"])).total_seconds() / 3600
            if hours > cfg["max_hours"]:
                bad.append(f"{dev} last check-in {hours:.0f} h ago")
            else:
                ok.append(f"{dev} {hours:.1f}h")
    if bad:
        return False, "; ".join(bad), ""
    return True, f"{len(ok)} devices checked in, rules v{status.get('version')}", ", ".join(ok)


def count_deliveries(rule, now, today):
    """(orders this week, hours since Pocket Ledger synced, sorted (service, date) list)."""
    root = Path(rule["ledger"])
    plaid = json.loads((root / "plaid.json").read_text(encoding="utf-8"))
    stamps = [parse_utc(s) for s in (plaid.get("lastSync"), plaid.get("sfLast")) if s]
    age = (now - max(stamps)).total_seconds() / 3600 if stamps else float("inf")
    start, end = monday_of(today).isoformat(), today.isoformat()
    keys = [norm(m) for m in rule["merchants"] if norm(m)]
    orders = set()
    for f in sorted((root / "ptx").glob("*.json")):
        for t in json.loads(f.read_text(encoding="utf-8")):
            d = t.get("d") or ""
            if not (start <= d <= end) or (t.get("amt") or 0) <= 0:      # this week, money out
                continue
            text = norm(f"{t.get('m', '')} {t.get('desc', '')}")
            hit = next((k for k in keys if k in text), None)
            if hit:
                orders.add((hit, d))
    return len(orders), age, sorted(orders)


def rule_deliveries(rule, now, today):
    limit = int(rule.get("max_per_week", 1))
    try:
        n, age, orders = count_deliveries(rule, now, today)
    except (OSError, ValueError, KeyError) as e:
        return False, "Pocket Ledger data unreadable", f"{e.__class__.__name__}: {e}"
    if age > float(rule.get("max_sync_age_hours", 48)):
        when = "never" if age == float("inf") else f"{age:.0f} h ago"
        return False, f"Pocket Ledger last synced {when}", "open Pocket Ledger on the PC so it syncs"
    return n <= limit, f"deliveries this week {n} of {limit}", ", ".join(f"{k} {d}" for k, d in orders)


def days_logged(data, week_start):
    """Training days fully logged in Block Trainer during the week starting [week_start]."""
    end = week_start + timedelta(days=7)
    seen = set()
    for c in (data or {}).get("completions", []):
        try:
            d = parse_utc(c["at"]).astimezone().date()
        except (KeyError, ValueError, TypeError):
            continue
        if week_start <= d < end:
            seen.add((c.get("block"), c.get("day"), c.get("week")))
    return len(seen)


def rule_workouts(rule, data, today):
    start = date.fromisoformat(rule["start"])
    if today < start:
        return True, f"workouts count from {start}", ""
    per_week = int(rule.get("days_per_week") or (data or {}).get("days_per_week") or 0)
    if per_week <= 0:
        return False, "no training block reported by Block Trainer", "open Block Trainer on the phone"
    monday = monday_of(today)
    last_monday = monday - timedelta(days=7)
    if last_monday >= start:
        last = days_logged(data, last_monday)
        if last < per_week and today == monday:
            return False, f"workouts last week {last} of {per_week}", "every training day needs all its sets logged"
    return True, f"workouts this week {days_logged(data, monday)} of {per_week}", ""


def rule_weight(rule, data, today):
    start = date.fromisoformat(rule["start"])
    if today < start:
        return True, f"weight counts from {start}", ""
    dates = {str(e.get("date", ""))[:10] for e in (data or {}).get("bodyweight", [])}
    if today.isoformat() in dates:
        return True, "weight logged today", ""
    return False, "no weight logged today", "log it in Block Trainer's bodyweight screen"


def rule_steps(rule, data, today):
    start = date.fromisoformat(rule["start"])
    day = today - timedelta(days=1)
    if day < start:
        return True, f"steps count from {start}", ""
    need = int(rule.get("min", 10000))
    if not data:
        return False, "no step counts from the phone", "allow steps in Fortress Agent (Health Connect)"
    try:
        read_on = parse_utc(data["at"]).astimezone().date()
    except (KeyError, ValueError, TypeError):
        read_on = None
    if read_on is None or read_on <= day:
        return False, f"steps for {day} not read since midnight", "the phone checks in every 15 minutes at home"
    counts = {}
    for d in data.get("days", []):
        try:
            counts[str(d.get("date", ""))[:10]] = int(d.get("steps") or 0)
        except (TypeError, ValueError):
            continue
    n = counts.get(day.isoformat())
    if n is None:
        return False, f"no step count for {day}", "check Gadgetbridge syncs to Health Connect"
    return n >= need, f"steps {day} {n:,} of {need:,}", ""


# ---- one run ----------------------------------------------------------------------------

def evaluate(cfg, now, today, status, reports):
    """[(name, passed, summary, detail)] for every rule this config turns on."""
    results = [("devices",) + rule_devices(cfg, now, status)]
    if "deliveries" in cfg:
        results.append(("deliveries",) + rule_deliveries(cfg["deliveries"], now, today))
    if "workouts" in cfg:
        data = latest_report(reports, cfg["workouts"].get("source", "block_trainer"))
        results.append(("workouts",) + rule_workouts(cfg["workouts"], data, today))
    if "weight" in cfg:
        data = latest_report(reports, cfg["weight"].get("source", "block_trainer"))
        results.append(("weight",) + rule_weight(cfg["weight"], data, today))
    if "steps" in cfg:
        data = latest_report(reports, cfg["steps"].get("source", "steps"))
        results.append(("steps",) + rule_steps(cfg["steps"], data, today))
    return results


def decide(results, today, state):
    """'already' (posted earlier today), 'fail' or 'post'."""
    if state.get("days", {}).get(today.isoformat()) == "posted":
        return "already"
    return "fail" if any(not r[1] for r in results) else "post"


def post(cfg, comment, today):
    token, user = cfg.get("auth_token", ""), cfg.get("username", "")
    if not token or token.startswith("PASTE") or not user or user.startswith("YOUR"):
        return False, "set username and auth_token in config.json"
    url = (f"https://www.beeminder.com/api/v1/users/{urllib.parse.quote(user)}/goals/"
           f"{urllib.parse.quote(cfg['goal'])}/datapoints.json")
    body = urllib.parse.urlencode({
        "auth_token": token, "value": 1, "comment": comment, "requestid": f"fortress-{today:%Y%m%d}",
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=30):
            return True, "posted"
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")[:200]
        if "duplicate" in text.lower():
            return True, "already on Beeminder"
        return False, f"Beeminder said {e.code}: {text}"
    except OSError as e:
        return False, f"could not reach Beeminder: {e}"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    dry = "--dry-run" in argv
    cfg_path = Path(argv[argv.index("--config") + 1]) if "--config" in argv else HERE / "config.json"
    folder = cfg_path.resolve().parent
    log = Log(folder / "beeminder-log.txt")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    state_path = folder / "beeminder-state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}

    now = datetime.now(timezone.utc)
    today = datetime.now().astimezone().date()
    core = cfg.get("core", CORE)
    status = fetch_json(core + "/status")
    reports = fetch_json(core + "/reports") if any(k in cfg for k in ("workouts", "weight", "steps")) else None

    results = evaluate(cfg, now, today, status, reports)
    for name, passed, summary, detail in results:
        log(f"  {'PASS' if passed else 'FAIL'} {name}: {summary}" + (f" [{detail}]" if detail else ""))
    outcome = decide(results, today, state)
    posted = False
    comment = "; ".join(r[2] for r in results)   # counts only; details stay in this log

    code = 0
    if outcome == "already":
        log("OK, today's point is already posted")
    elif outcome == "fail":
        log("FAIL, nothing posted: " + ", ".join(r[0] for r in results if not r[1]))
        code = 1
    elif dry:
        log(f"DRY RUN OK, would post 1: {comment}")
    else:
        ok, msg = post(cfg, comment, today)
        log(f"POSTED 1 ({msg}): {comment}" if ok else f"FAIL: {msg}")
        posted = ok
        if not ok:
            code = 2

    if posted:
        state.setdefault("days", {})[today.isoformat()] = "posted"
        cutoff = (today - timedelta(days=30)).isoformat()
        state["days"] = {d: v for d, v in state["days"].items() if d >= cutoff}
        try:
            state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
        except OSError as e:
            log(f"could not save state: {e}")
    return code


if __name__ == "__main__":
    sys.exit(main())
