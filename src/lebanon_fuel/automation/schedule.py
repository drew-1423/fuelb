"""Timezone-aware scheduling policy. Watch windows are operational assumptions."""
from datetime import datetime, time
from zoneinfo import ZoneInfo
import tomllib

SOURCES = ("ipt", "ministry", "taqtek", "eia", "ec", "fed")


def settings(root):
    config = tomllib.loads((root / "config/automation.toml").read_text())
    schedule = config["schedule"]
    ZoneInfo(schedule["timezone"])
    if not 60 <= schedule["poll_seconds"] <= 86400:
        raise ValueError("Scheduler poll must be between 60 and 86400 seconds")
    for key in ("regular_interval_minutes", "window_interval_minutes"):
        if schedule[key] < 30:
            raise ValueError("Refresh intervals must be at least 30 minutes")
    if any(day not in range(7) for day in schedule["window_weekdays"]):
        raise ValueError("Watch weekdays use Monday=0 through Sunday=6")
    for window in schedule["announcement_windows"]:
        start, end = map(time.fromisoformat, window.split("-"))
        if start >= end:
            raise ValueError("Watch windows must start before end on the same local day")
    for source in SOURCES:
        if config["collection"]["minimum_interval_minutes"][source] < 30:
            raise ValueError("Source refresh minimum is 30 minutes")
    if not 1 <= config["collection"]["ministry_lookback_days"] <= 3650:
        raise ValueError("Invalid ministry lookback")
    if not 30 <= config["collection"]["timeout_seconds"] <= 1800:
        raise ValueError("Invalid collector timeout")
    if config["collection"]["access_failure_pause_hours"] < 1:
        raise ValueError("Access-denial cooldown must be at least one hour")
    if config["monitoring"]["minimum_outcomes"] < 20:
        raise ValueError("Monitoring requires at least 20 independent target outcomes")
    if config["monitoring"]["window_outcomes"] < config["monitoring"]["minimum_outcomes"]:
        raise ValueError("Monitoring window is shorter than its required outcome count")
    return config


def due(at, previous, schedule):
    if at.utcoffset() is None:
        raise ValueError("Scheduler requires an aware clock")
    local = at.astimezone(ZoneInfo(schedule["timezone"]))
    watch = local.weekday() in schedule["window_weekdays"] and any(
        time.fromisoformat(window.split("-")[0]) <= local.time().replace(tzinfo=None)
        < time.fromisoformat(window.split("-")[1]) for window in schedule["announcement_windows"])
    minutes = schedule["window_interval_minutes"] if watch else schedule["regular_interval_minutes"]
    return (previous is None or (at - datetime.fromisoformat(previous)).total_seconds() >= 60 * minutes,
            "announcement_watch_window" if watch else "regular")
