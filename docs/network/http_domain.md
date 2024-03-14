# `HttpDomain`

An `HttpDomain` allows sending ad hoc HTTP2-enabled requests via [`httpx`](https://pypi.org/project/httpx/)
while sharing session state back and forth with a `Page`.

Unlike `FetchDomain`, it is not sensitive to the CORS policy on the parent page.

## Usage

An `HttpDomain` object is initialised with every new `Page` on first use. It is bound to it under
`Page.http_domain`. A shortcut is available, too, via `Page.http()`.

You can also control the initialisation of the session via `Page.make_http_domain`, though
that is entirely optional. Cookies and user-agent will be set automatically.

The most basic example.
 

Using the `HttpDomain` to get pages after a login is completed via the browser.
```python
from mokr import launch

async def main():
    async with launch() as browser:
        page = await browser.first_page()
        response = await page.http(
            "https://some.site/login",
            method="post",
            json={"user": "me", "pass": "secret"},
        )
        if response.ok:
            # Cookies will automatically have been applied after http request.
            await page.goto("https://some.site/protected/endpoint")

asyncio.run(main())
```

Inverse of the above: navigate to a page, use browser to run a login process, and
then use the domain to get protected pages.

```python
import asyncio
from mokr import launch

async def main():
    async with launch() as browser:
        page = await browser.first_page()
        await page.goto("https://some.site/login")
        # Do the login process here...!
        # Now protected URLs are accessible via HttpDomain.
        link_elements = await page.query_selector_all("a")
        for link_element in link_elements:
            html = await link_element.content()
            # Here parse would be a utilty written by you.
            url = parse(html)
            response = await page.http(url)
            content = await response.content()
            print(content)

asyncio.run(main())
```
