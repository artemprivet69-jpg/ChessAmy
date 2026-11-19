import re
import uuid

import pytest

pytestmark = pytest.mark.e2e


def register(page, base):
    page.goto(base + "/")
    page.click('.auth-tab[data-tab="register"]')
    name = "e2e" + uuid.uuid4().hex[:8]
    page.fill("#register-username", name)
    page.fill("#register-password", "pass1234")
    page.click('#register-form button[type="submit"]')
    page.wait_for_selector("#recovery-modal:not(.hidden)")
    code = page.inner_text("#recovery-code-value").strip()
    page.click("#recovery-done")
    page.wait_for_url("**/coach")
    return name, code


def choose_coach(page):
    page.click('[data-coach-id="1"]')
    page.click("#coach-confirm")
    page.click("#coach-confirm-yes")
    page.wait_for_url("**/menu")


def test_register_shows_recovery_code(browser, server):
    page = browser.new_page()
    _, code = register(page, server)
    assert re.fullmatch(r"AMY-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}", code)
    page.close()


def test_theme_setting_persists(browser, server):
    page = browser.new_page()
    register(page, server)
    choose_coach(page)
    page.goto(server + "/profile")
    page.select_option("#ui-theme", "dark")
    page.uncheck("#ui-sound")
    page.click("#save-ui")
    page.wait_for_timeout(600)
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    page.reload()
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    assert page.evaluate("document.documentElement.dataset.sound") == "off"
    page.close()
