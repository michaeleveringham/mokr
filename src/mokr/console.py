import asyncio
from argparse import ArgumentParser

from mokr import launch
from mokr.constants import LIFECYCLE_EVENTS
from mokr.download import ensure_binary, install_binary


async def scrape(
    browser_type: str,
    url: str,
    headless: bool,
    timeout: int,
    wait_until: LIFECYCLE_EVENTS,
    user_agent: str | None,
    proxy: str | None,
    output_file: str | None,
) -> None:
    """
    Run a simple scrape of a URL.

    Args:
        browser_type (str): Either "chrome" or "firefox".
        url (str): Target URL to navigate to.
        headless (bool): Run in headles mode, if True.
        timeout (int): Tiem to wait in milliseconds for page load.
        wait_until (LIFECYCLE_EVENTS): Condition to wait for.
        user_agent (str | None): User agent to override page with.
        proxy (str | None): Remote proxy to use.
        output_file (str | None): Output file.

    Raises:
        SystemExit: Raised if any error encountered to set exit code to 1.
    """
    try:
        launcher = launch(
            browser_type=browser_type,
            headless=headless,
            proxy=proxy,
        )
        browser = await launcher.launch()
        page = await browser.first_page()
        if user_agent:
            await page.set_user_agent(user_agent)
        response = await page.goto(url, timeout=timeout, wait_until=wait_until)
        if browser_type == "chrome":
            html = await response.content()
        else:
            html = (
                "Firefox does not support accessing response body."
                f" Response result: {response.status}: {response.reason}"
            )
        print(html)
        await browser.close()
        if output_file:
            with open(output_file, "w") as f:
                f.write(html)
    except Exception as error:
        print(f"Failed to scrape! Error: {error}")
        raise SystemExit(1)


def main() -> None:
    parser = ArgumentParser("mokr", description="A remote-controlled browser.")
    subparsers = parser.add_subparsers(dest="command")
    install_parser = subparsers.add_parser(
        "install",
        description="Install required browser."
    )
    install_parser.add_argument(
        "--force",
        help="Don't check first, just force install.",
        action="store_true",
    )
    install_parser.add_argument(
        "--type",
        help="Type of browser to install. If omitted, installs all.",
        choices=["chrome", "firefox"],
        dest="browser_type",
    )
    scrape_parser = subparsers.add_parser(
        "scrape",
        description="Run a browser session, navigate to a URL, and dump HTML.",
    )
    scrape_parser.add_argument(
        "url",
        help="Target URL to scrape.",
        type=str,
    )
    scrape_parser.add_argument(
        "--type",
        help="Type of browser to use.",
        choices=["chrome", "firefox"],
        dest="browser_type",
        default="chrome",
    )
    scrape_parser.add_argument(
        "--headful",
        help="Run in headful (not headless) browser.",
        action="store_true",
    )
    scrape_parser.add_argument(
        "--timeout",
        help="Time in milliseconds to wait for page to load.",
        type=int,
        default=30000,
    )
    scrape_parser.add_argument(
        "--wait-until",
        help="Wait until a specific lifecycle event occurs.",
        type=str,
        default="load",
    )
    scrape_parser.add_argument(
        "--user-agent",
        help="User agent to override the page with.",
        type=str,
        default=None,
    )
    scrape_parser.add_argument(
        "--proxy",
        help="Remote proxy to use.",
        type=str,
        default=None,
    )
    scrape_parser.add_argument(
        "--output-file",
        help="Dump HTML content to given file.",
        type=str,
        default=None,
    )
    options = parser.parse_args()
    if options.command == "install":
        browser_types = (
            [options.browser_type] if options.browser_type
            else ["chrome", "firefox"]
        )
        for browser_type in browser_types:
            if options.force or not ensure_binary(browser_type):
                install_binary(browser_type)
            else:
                print(f"{browser_type.title()} browser already installed.")
    elif options.command == "scrape":
        asyncio.run(
            scrape(
                options.browser_type,
                options.url,
                not options.headful,
                options.timeout,
                options.wait_until,
                options.user_agent,
                options.proxy,
                options.output_file,
            )
        )
