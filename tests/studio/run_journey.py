"""Synchronize the immutable-run navigation before observing its outcome."""


def rerun_saved_inputs(page):
    previous = page.url
    history = previous.rsplit("/", 1)[0] + "/"
    page.get_by_role("button", name="Rerun saved inputs").click()
    page.wait_for_url(lambda url: url.startswith(history) and url != previous)
