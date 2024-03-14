# Browser Automation Comparisons

There are other fantastic browser automation projects, below will compare and contrast
them to `mokr`.

## Notable Changes from Pyppeteer

While forked from `pyppeteer`, there are some notable changes beyond reformating,
refactoring, and restructuring! Including, but not limited to...

Changed:
  - The `NetworkManager` has been overhauled. The new Chrome implementation is based off of
  `puppeteer` heavily, but is not 1:1 with it. It uses the
  [fetch domain](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/) instead
  of just the [network domain](https://chromedevtools.github.io/devtools-protocol/tot/Network/).
  - Request interception is enabled by default. Can be disabled with 
  `Page.set_request_interception_enabled(False)` (on Chrome, Firefox is always on).
  - `Browser.create` has been replaced with `Browser.ready` and accepts no keyword arguments.
  This means a `Browser` can be instantied and target discovery postponed until
  `.ready()` is called.
  - The `launch` method is top-level and offers an async context manager to better handle
  graceful exits.
  - Firefox only: Temporary extensions can be installed at browser launch.
  - `CDPSession` is now `DevtoolsSession` and shares a base class with `Connection`,
  called `RemoteConnection`.

New:
  - Partial Firefox support.
  - There is a new class, `FetchDomain` that can be used to send fetch requests
  via `Page.fetch` (this calls the page's instantiated `FetchDomain` object).
  - Another new class, `HttpDomain` is available to send ad hoc requests via an
  `httpx`, HTTP2-enabled, client that syncs it's cookies with the parent `Page` and
  vice-versa.
  - Proxy support is baked-in, meaning you can pass a `proxy` string to `mokr.launch` directly.
  - New `EventWaiter` class; based off of `pyppeteer.helper.waitForEvent` method.

Removed:
  - Tracing has been removed.
  - `ElementHandle.querySelectorEval` and `.querySelectorAllEval` have been removed.

## Compared

Huge thanks are owed to the contributors of all the below projects, without them,
this project would be quite different.

The disadvantages below are not a knock on any of these projects or their contributors.

<table>
  <tbody>
    <tr>
      <th align="center">Package</th>
      <th align="center">Advantages</th>
      <th align="center">Disadvantages</th>
    </tr>
    <tr>
      <td><a href="https://github.com/microsoft/playwright-python">playwright-python</a></td>
      <td>
        <ul>
          <li>Well-maintained as owned by Microsoft.</li>
          <li>Offers syncronous and asyncronous APIs.</li>
          <li>Offers a fantastic request context.</li>
          <li>Supports Firefox fully.</li>
        </ul>
      </td>
      <td>
        <ul>
          <li>
            Can be difficult to debug in Python.
            <ul>
                <li>Remote calls are made to the local playwright server, not to the browser directly.</li>
                <li>APIs are generated, so digging into a method requires searching, or an actively running session, depending on your IDE.</li>
            </ul>
          </li>
          <li>Sync API is actually still running async code under-the-hood, which can lead to out-of-state browser pages and other unexpected behaviours.</li>
        </ul>
      </td>
    </tr>
    <tr>
      <td><a href="https://github.com/puppeteer/puppeteer">puppeteer</a></td>
      <td>
        <ul>
          <li>Well-maintained, easily the largest Node.js browser automation library.</li>
          <li>Working to support <a href="https://developer.chrome.com/blog/webdriver-bidi">BiDi</a>.</li>
        </ul>
      </td>
      <td>
        <ul>
          <li>Written in Node.js, does not mesh with a Python ecosystem.</li>
        </ul>
      </td>
    </tr>
    <tr>
      <td><a href="https://github.com/pyppeteer/pyppeteer">pyppeteer</a></td>
      <td>
        <ul>
          <li>Ported directly from puppeteer.</li>
        </ul>
      </td>
      <td>
        <ul>
          <li><b>No longer maintained!</b></li>
          <li>Does not use the fetch domain for request interception, resulting in unexpected behaviours with redirects in Chromium.</li>
          <li>Not "pythonic" in some ways, with a fair amount of duplicated code and camelCase variables (likely due to being a port).</li>
        </ul>
      </td>
    </tr>
  </tbody>
</table>