"""youtube_download.py — automates YouTube's own native Download button
(the "..." more-actions menu on a video page), when that video has it enabled.

IMPORTANT LIMITATIONS:
- YouTube's Download button only appears for SOME videos (uploader must
  enable offline access) — not available on every video/drama/channel.
- If not found within timeout, returns a clear message instead of failing
  silently or clicking the wrong thing.
"""
from __future__ import annotations

import os
import time
import threading
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

YT_PROFILE = os.path.join(os.path.expanduser("~"), "saathi_yt_profile")

_lock = threading.RLock()
_driver = None


class YtDownloadError(Exception):
    """Clear, speakable error."""


def _alive(d) -> bool:
    try:
        _ = d.title
        return True
    except Exception:
        return False


def _get_driver():
    global _driver
    if _driver is not None and _alive(_driver):
        return _driver
    opts = EdgeOptions()
    opts.add_argument(f"--user-data-dir={YT_PROFILE}")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--log-level=3")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--remote-debugging-port=0")
    try:
        _driver = webdriver.Edge(options=opts)
        return _driver
    except Exception as e:
        raise YtDownloadError(f"Browser launch failed: {type(e).__name__}")


def download_video(query: str) -> str:
    """Search YouTube for `query`, open the first result, try the native
    Download button. Returns a clear success or failure message."""
    with _lock:
        try:
            d = _get_driver()
        except YtDownloadError as e:
            return f"YouTube download error: {e}"

        try:
            search_url = f"https://www.youtube.com/results?search_query={quote(query)}"
            d.get(search_url)

            try:
                first = WebDriverWait(d, 15).until(
                    EC.element_to_be_clickable((By.ID, "video-title"))
                )
                first.click()
            except TimeoutException:
                return f"'{query}' YouTube par nahi mila (search result nahi aaya)."

            time.sleep(3)

            more_xpaths = [
                '//button[@aria-label="More actions"]',
                '//tp-yt-paper-icon-button[@aria-label="More actions"]',
                '//yt-icon-button[@id="button-shape"]//button[contains(@aria-label,"More")]',
            ]
            more_btn = None
            for xp in more_xpaths:
                try:
                    more_btn = WebDriverWait(d, 6).until(
                        EC.element_to_be_clickable((By.XPATH, xp))
                    )
                    break
                except TimeoutException:
                    continue

            if more_btn is None:
                return ("Download option is video ke liye nahi mila (three-dot menu "
                        "nahi khula). YouTube har video par download allow nahi karta.")

            more_btn.click()
            time.sleep(1)

            download_xpaths = [
                '//yt-formatted-string[text()="Download"]',
                '//tp-yt-paper-item[.//yt-formatted-string[contains(text(),"Download")]]',
                '//*[contains(text(),"Download")]',
            ]
            download_item = None
            for xp in download_xpaths:
                try:
                    download_item = WebDriverWait(d, 5).until(
                        EC.element_to_be_clickable((By.XPATH, xp))
                    )
                    break
                except TimeoutException:
                    continue

            if download_item is None:
                return ("Ye video download allow nahi karta — YouTube ka Download "
                        "button sirf kuch chuni hui videos par hota hai, is par nahi tha.")

            download_item.click()
            time.sleep(2)
            return f"'{query}' ke liye download shuru kar diya (agar YouTube ne allow kiya)."

        except Exception as e:
            return f"YouTube download error: {type(e).__name__}: {str(e)[:150]}"