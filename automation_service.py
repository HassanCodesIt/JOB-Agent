import sys
import asyncio
import hashlib
import os
from typing import Any

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from playwright.async_api import async_playwright


class AutomationService:
    def __init__(self):
        self.screenshots_dir = "screenshots"
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def _url_token(self, url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]

    def _screenshot_path(self, prefix: str, url: str) -> str:
        return os.path.join(self.screenshots_dir, f"{prefix}_{self._url_token(url)}.png")

    async def detect_form(self, url: str) -> tuple[list[dict[str, Any]] | str, str]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)

                # Detect CAPTCHA or human verification pages.
                content = (await page.content()).lower()
                blocked_keywords = [
                    "captcha",
                    "verify you are human",
                    "human verification",
                    "security check",
                    "are you a robot",
                ]
                is_blocked = any(keyword in content for keyword in blocked_keywords)

                if is_blocked:
                    screenshot_path = self._screenshot_path("blocked", url)
                    await page.screenshot(path=screenshot_path, full_page=True)
                    return "blocked", screenshot_path

                form_data: list[dict[str, Any]] = []
                inputs = await page.query_selector_all(
                    "input:not([type='hidden']), textarea, select"
                )
                for input_element in inputs:
                    name = await input_element.get_attribute("name") or ""
                    placeholder = await input_element.get_attribute("placeholder") or ""
                    tag_name = await input_element.evaluate("el => el.tagName.toLowerCase()")
                    type_attr = await input_element.get_attribute("type") or (
                        "select" if tag_name == "select" else "text"
                    )

                    # Try to find associated label text by id.
                    id_attr = await input_element.get_attribute("id")
                    label_text = ""
                    if id_attr:
                        label = await page.query_selector(f'label[for="{id_attr}"]')
                        if label:
                            label_text = await label.inner_text()

                    form_data.append(
                        {
                            "name": name,
                            "placeholder": placeholder,
                            "type": type_attr,
                            "label": label_text.strip(),
                            "id": id_attr,
                        }
                    )

                screenshot_path = self._screenshot_path("form", url)
                await page.screenshot(path=screenshot_path, full_page=True)
                return form_data, screenshot_path
            finally:
                await browser.close()

    async def fill_form(
        self, url: str, field_mapping: dict[str, Any], resume_path: str | None = None
    ) -> bool:
        """
        field_mapping: { "selector": "value", ... }
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)

                # Fill values with selector-specific handling.
                for selector, value in field_mapping.items():
                    value_str = str(value)
                    try:
                        locator = page.locator(selector).first
                        await locator.wait_for(state="attached", timeout=10000)
                        tag_name = await locator.evaluate("el => el.tagName.toLowerCase()")
                        if tag_name == "select":
                            await locator.select_option(label=value_str)
                        else:
                            await locator.fill(value_str)
                    except Exception as e:
                        print(f"Failed to fill {selector}: {e}")

                # Handle resume upload if path exists.
                if resume_path and os.path.exists(resume_path):
                    try:
                        file_inputs = await page.query_selector_all("input[type='file']")
                        for file_input in file_inputs:
                            id_attr = await file_input.get_attribute("id")
                            label_text = ""
                            if id_attr:
                                label = await page.query_selector(f'label[for="{id_attr}"]')
                                if label:
                                    label_text = (await label.inner_text()).lower()

                            if "resume" in label_text or "cv" in label_text:
                                await file_input.set_input_files(resume_path)
                                print(f"Uploaded resume to {id_attr}")
                    except Exception as e:
                        print(f"Failed to upload resume: {e}")

                print("Form filled with mapping and resume. Human review required for submission.")
                # Keep browser open for user to review and submit manually.
                await asyncio.sleep(60)
                return True
            finally:
                await browser.close()

automation_service = AutomationService()
