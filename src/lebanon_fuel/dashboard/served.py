"""Public snapshot status and non-blocking startup."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import escape
import logging
import os
from pathlib import Path
import sqlite3
import tarfile
from threading import Lock
import time

import streamlit as st

from lebanon_fuel.automation import dashboard_snapshot as cloud
from . import data

LOGGER = logging.getLogger(__name__)


@st.cache_data(ttl=120, show_spinner=False)
def latest_publication():
    try:
        return cloud.canonical_publication()
    except (OSError, ValueError, KeyError, TypeError):
        LOGGER.warning("Could not check the canonical publication", exc_info=True)
        return None


@st.cache_resource
def workers():
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="fuel-publication"), Lock(), {}


def restore_job(root, record):
    executor, lock, jobs = workers()
    key = (root, record["identity"])
    with lock:
        now = time.monotonic()
        for identity, (future, started) in list(jobs.items()):
            if future.done() and now - started >= 120:
                jobs.pop(identity)
        if key not in jobs:
            jobs[key] = executor.submit(cloud.restore, root, record), now
        return jobs[key][0]


def report_path(root, relative):
    relative = Path(relative)
    loaded = st.session_state.get("_report_snapshot_root")
    if loaded and relative in cloud.REPORTS:
        return Path(loaded) / relative
    return root / relative


def public_status(record, canonical, state):
    tag = escape(record["tag"] if record else "")
    identity = escape(record["identity"] if record else "")
    latest = escape(canonical["tag"] if canonical else "")
    loaded_at = escape(record["created_at"] if record else "")
    st.html(f'<span id="fuel-publication" data-served-release="{tag}" data-snapshot-id="{identity}" '
            f'data-latest-release="{latest}" data-served-at="{loaded_at}" data-publication-state="{escape(state)}"></span>')
    if record:
        st.caption(f"Loaded snapshot · {record['tag']} · {data.beirut_time(record['created_at'])}")
    if canonical:
        st.caption(f"Latest verified publication · {data.beirut_time(canonical['created_at'])}")
    if state == "behind":
        hours = (datetime.fromisoformat(canonical["created_at"]) -
                 datetime.fromisoformat(record["created_at"])).total_seconds() / 3600
        st.warning(f"An earlier snapshot is loaded. The latest verified publication is {hours:.1f} hours newer.")
        st.link_button("Open latest public price summary", cloud.PUBLIC_SUMMARY)
    elif state == "unverified":
        st.caption("Could not check the latest publication. The loaded snapshot keeps its original dates.")
    elif state == "behind_failed":
        st.warning("A newer publication exists, but its database failed verification or download. "
                   "The loaded prices retain their original dates.")
        st.link_button("Open latest public price summary", cloud.PUBLIC_SUMMARY)
    elif state == "failed":
        st.warning("The newest database download failed. The loaded snapshot keeps its original dates.")
        st.link_button("Open latest public price summary", cloud.PUBLIC_SUMMARY)
    if record:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(record["created_at"])
        if age.total_seconds() > 12 * 3600:
            st.warning(f"The loaded publication is {age.total_seconds() / 3600:.0f} hours old.")


@st.fragment(run_every=2)
def _wait_for_database(root, record):
    if restore_job(root, record).done():
        st.rerun(scope="app")
    st.info("Verifying and loading the published price database. This can take a moment after startup.")


def _summary(root, local, canonical, failed):
    st.title("Lebanon gasoline 95")
    st.caption("Published summary · LBP per 20 L · Beirut time")
    if local:
        try:
            price, _, issued = cloud.verified_widget(root / cloud.publication.WIDGET, local)
            if price is not None:
                st.metric("Recorded price in this publication", f"{price:,} LBP")
            if issued:
                st.caption("Summary issued · " + data.beirut_time(datetime.fromtimestamp(issued, timezone.utc)))
            st.caption("Summary publication · " + data.beirut_time(local["created_at"]))
        except (OSError, KeyError, ValueError):
            LOGGER.warning("Bundled summary could not be verified", exc_info=True)
    public_status(None, canonical, "unavailable" if failed else "hydrating")
    st.link_button("Open public price summary", cloud.PUBLIC_SUMMARY)


def select_snapshot(root):
    """Choose one complete generation. Never mix report and database generations."""
    st.session_state["_report_snapshot_root"] = None
    pointer = root / cloud.publication.POINTER
    if (data.refresh_writer(root) != "github_actions" or not pointer.is_file()
            or os.environ.get("LEBANON_FUEL_LOCAL_STORAGE") == "1"):
        return root
    try:
        local = cloud.repository_publication(root)
    except (OSError, ValueError, KeyError, TypeError):
        local = None
    canonical = latest_publication()
    if canonical and local and datetime.fromisoformat(canonical["created_at"]) < datetime.fromisoformat(local["created_at"]):
        # An upstream cache may serve an older pointer. Do not roll back.
        canonical = None
    preferred = canonical or local
    cached = cloud.previous_snapshot(root, before=datetime.now(timezone.utc).isoformat())
    if (cached and (not preferred or datetime.fromisoformat(cached[1]['created_at']) >
                    datetime.fromisoformat(preferred['created_at']))):
        preferred, canonical = cached[1], None
    if not preferred:
        _summary(root, local, canonical, True)
        st.error("No verified snapshot is available.")
        return None
    future = restore_job(root, preferred)
    failed = False
    if future.done():
        try:
            path = future.result()
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error, tarfile.TarError):
            LOGGER.warning("Snapshot restoration failed", exc_info=True)
            failed = True
        else:
            st.session_state["_report_snapshot_root"] = path
            public_status(preferred, canonical, "current" if canonical else "unverified")
            return path
    fallback = cloud.previous_snapshot(root, before=preferred["created_at"])
    if fallback:
        path, record = fallback
        st.session_state["_report_snapshot_root"] = path
        if canonical and record["tag"] != canonical["tag"]:
            state = "behind_failed" if failed else "behind"
        else:
            state = "failed" if failed else "unverified"
        public_status(record, canonical, state)
        if not future.done():
            _wait_for_database(root, preferred)
        return path
    _summary(root, local, canonical, failed)
    if failed:
        st.error("The full snapshot could not be loaded. Reload to retry or open the public price summary.")
    else:
        _wait_for_database(root, preferred)
    return None
