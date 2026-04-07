from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
import re
from time import monotonic
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

class SaveSubsTranscriptError(RuntimeError):
    pass


class SaveSubsTranscriptService:
    def __init__(
        self,
        timeout_seconds: int = 45,
        *,
        headless: bool = False,
        browser_channel: str = "chrome",
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.headless = True
        self.browser_channel = browser_channel.strip()
        self.base_urls = [
            "https://savesubs.com/",
            "https://savesubs.com/sites",
        ]

    async def fetch_transcript(self, youtube_url: str) -> str | None:
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except Exception as exc:  # pragma: no cover
            raise SaveSubsTranscriptError(
                "Playwright is not installed. Install project requirements and run `playwright install chromium` to enable SaveSubs fallback."
            ) from exc

        async def _run() -> str | None:
            async with async_playwright() as playwright:
                browser = await _launch_browser(
                    playwright,
                    headless=self.headless,
                    browser_channel=self.browser_channel,
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1440, "height": 900},
                    locale="en-US",
                )
                page = await context.new_page()
                try:
                    last_error: Exception | None = None
                    for base_url in self.base_urls:
                        try:
                            await page.goto(base_url, wait_until="domcontentloaded")
                            await self._wait_for_form(page)
                            input_locator = await _find_input_locator(page)
                            if input_locator is None:
                                raise SaveSubsTranscriptError("SaveSubs input field was not found after the page loaded.")

                            await input_locator.fill(youtube_url)
                            await page.wait_for_timeout(800)

                            clicked = await _click_submit(page, input_locator)
                            if not clicked:
                                await input_locator.press("Enter")

                            try:
                                await page.wait_for_load_state("networkidle", timeout=self.timeout_seconds * 1000)
                            except PlaywrightTimeoutError:
                                pass

                            transcript = await self._poll_for_transcript(page, base_url=base_url)
                            if transcript:
                                return transcript
                        except Exception as exc:
                            last_error = exc
                            continue
                    if last_error is not None:
                        raise SaveSubsTranscriptError(f"All SaveSubs page variants failed. Last error: {last_error}")
                    return None
                finally:
                    with contextlib.suppress(Exception):
                        if not page.is_closed():
                            await page.close()
                    with contextlib.suppress(Exception):
                        await context.close()
                    with contextlib.suppress(Exception):
                        await browser.close()

        try:
            return await asyncio.wait_for(_run(), timeout=self.timeout_seconds + 5)
        except asyncio.TimeoutError as exc:
            raise SaveSubsTranscriptError("SaveSubs fallback timed out.") from exc
        except SaveSubsTranscriptError:
            raise
        except Exception as exc:
            logger.warning("SaveSubs Playwright fallback failed unexpectedly: %s", exc)
            raise SaveSubsTranscriptError(f"SaveSubs Playwright fallback failed unexpectedly: {exc}") from exc

    async def _download_text(self, page, url: str) -> str:
        response = await page.context.request.get(url, timeout=self.timeout_seconds * 1000)
        if response.ok:
            text = await response.text()
            return _normalize_downloaded_transcript(text)
        return ""

    async def _poll_for_transcript(self, page, *, base_url: str) -> str | None:
        deadline = monotonic() + self.timeout_seconds
        tried_keys: set[str] = set()

        while monotonic() < deadline:
            page_text = await page.text_content("body") or ""
            transcript = _extract_transcript_from_text(page_text)
            if transcript:
                return transcript

            candidates = await _collect_candidate_controls(page)
            for candidate in candidates:
                text = candidate["text"]
                href = candidate["href"]
                key = f"{text}|{href}"
                if key in tried_keys:
                    continue
                tried_keys.add(key)

                if href and _looks_like_download_link(text, href):
                    full_url = urljoin(base_url, href)
                    downloaded = await self._download_text(page, full_url)
                    if downloaded:
                        return downloaded

                if candidate["clickable"] and _looks_like_click_target(text, href):
                    downloaded = await _click_for_transcript(page, candidate["locator"])
                    if downloaded:
                        return _normalize_downloaded_transcript(downloaded)
                    await page.wait_for_timeout(1200)
                    page_text = await page.text_content("body") or ""
                    transcript = _extract_transcript_from_text(page_text)
                    if transcript:
                        return transcript

            await page.wait_for_timeout(1200)

        raise SaveSubsTranscriptError("SaveSubs loaded, but no transcript or subtitle download controls produced usable text.")

    async def _wait_for_form(self, page) -> None:
        await page.wait_for_timeout(1500)
        with contextlib.suppress(Exception):
            await page.wait_for_selector("input, textarea, button", timeout=min(self.timeout_seconds, 15) * 1000)


async def _collect_candidate_controls(page) -> list[dict]:
    candidates: list[dict] = []
    selector_specs = [
        ("a[href]", True),
        ("button", True),
        ("[role='button']", True),
    ]
    for selector, clickable in selector_specs:
        locator = page.locator(selector)
        try:
            count = min(await locator.count(), 60)
        except Exception:
            continue
        for index in range(count):
            item = locator.nth(index)
            try:
                text = ((await item.inner_text(timeout=500)) or "").strip()
            except Exception:
                text = ""
            try:
                href = await item.get_attribute("href")
            except Exception:
                href = None
            candidates.append(
                {
                    "locator": item,
                    "text": text,
                    "href": href,
                    "clickable": clickable,
                }
            )
    return candidates


async def _find_input_locator(page):
    input_selectors = [
        'input[name="url"]',
        'input[type="url"]',
        'textarea[name="url"]',
        'textarea',
        'input[placeholder*="youtube" i]',
        'input[placeholder*="video" i]',
        'textarea[placeholder*="youtube" i]',
        "input",
    ]
    for selector in input_selectors:
        locator = page.locator(selector).first
        with contextlib.suppress(Exception):
            if await locator.count():
                return locator
    return None


async def _click_submit(page, input_locator) -> bool:
    submit_selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Generate")',
        'button:has-text("Generate Subtitles")',
        'button:has-text("Download")',
        'button:has-text("Search")',
        'button:has-text("Get")',
        'button:has-text("Start")',
    ]
    for selector in submit_selectors:
        locator = page.locator(selector).first
        with contextlib.suppress(Exception):
            if await locator.count():
                await locator.click()
                return True
    return False


def _looks_like_download_link(text: str, href: str) -> bool:
    combined = f"{text} {href}".lower()
    return any(token in combined for token in (".txt", ".srt", ".vtt", "txt", "srt", "vtt", "subtitle", "caption"))


def _looks_like_click_target(text: str, href: str | None) -> bool:
    combined = f"{text} {href or ''}".lower()
    return any(
        token in combined
        for token in (
            "txt",
            "srt",
            "vtt",
            "transcript",
            "subtitle",
            "caption",
            "english",
            "auto",
            "download",
            "edit",
        )
    )


async def _click_for_transcript(page, locator) -> str:
    with contextlib.suppress(Exception):
        async with page.expect_download(timeout=2500) as download_info:
            await locator.click(timeout=1500)
        download = await download_info.value
        download_path = await download.path()
        if download_path:
            return Path(download_path).read_text("utf-8", errors="ignore")

    with contextlib.suppress(Exception):
        await locator.click(timeout=1500)
    return ""


async def _launch_browser(playwright, *, headless: bool, browser_channel: str):
    launch_kwargs = {
        "headless": True,
        "slow_mo": 75,
    }
    if browser_channel:
        with contextlib.suppress(Exception):
            return await playwright.chromium.launch(channel=browser_channel, **launch_kwargs)
    return await playwright.chromium.launch(**launch_kwargs)


def _extract_transcript_from_text(page_text: str) -> str:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    useful: list[str] = []
    for line in lines:
        lowered = line.lower()
        if any(
            marker in lowered
            for marker in (
                "download",
                "language",
                "subtitle downloader",
                "privacy policy",
                "terms",
                "paste youtube url",
            )
        ):
            continue
        useful.append(line)
    return _normalize_downloaded_transcript("\n".join(useful))


def _normalize_downloaded_transcript(text: str) -> str:
    cleaned = text.replace("\r", "\n")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"\u200b", "", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) < 80:
        return ""
    return cleaned
