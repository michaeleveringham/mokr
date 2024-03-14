# Usage Examples

Basic usage; launch a headless browser, navigate to a site, and dump the html to console.
```python
import asyncio
from mokr import launch

async def main():
    async with launch() as browser:
        page = await browser.first_page()
        response = await page.goto("https://example.com")
        content = await response.content()
        print(content)
    
asyncio.run(main())
```

Now a more complex usage demonstrating request interception and fulfillment.

Here we'll launch the browser, and then hook some handlers to intercept requests and responses.
Next we navigate to the Wikipedia page for Python.

The request interception method `intercept_request` is called during as part of
the `mokr.network.Request` object's request interception callback chain.
We look for the request for the Python logo, and then make a new request for a picture of a python
snake instead.

Finally, we fulfill the original request with response from the snake-request.

```python
import asyncio
from mokr import launch
from mokr.network import Request, Response

async def main():
    snake_url = "https://upload.wikimedia.org/wikipedia/commons/3/32/Python_molurus_molurus_2.jpg"
    async with launch(headless=False) as browser:
        page = await browser.first_page()

        async def intercept_request(request: Request) -> Request | None:
            print(f"Intercepted request for: {request.url}")
            if request.url.endswith("Python-logo-notext.svg.png"):
                print("Getting a cute python picture to use as the new logo...")
                response = await page.fetch(snake_url)
                await request.fulfill(response)
            else:
                return request

        def log_response(response: Response) -> Request:
            print(f"Got {response.status} from: {response.url}")
        
        page.on("request", intercept_request)
        page.on("response", log_response)
        await page.goto("https://en.wikipedia.org/wiki/Python_(programming_language)")

asyncio.run(main())
```

Screenshot from running the above example.

![Screenshot from running the above example.](../images/usage-request-interception-example.png)