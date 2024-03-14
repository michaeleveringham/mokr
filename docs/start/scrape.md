# Scrape Command

You can quickly test a browser with a given URL via `mokr scrape`.

This will retrieve a webpage, and dump the contents to the console.
Optional arguments can be used to add some modifiers to wait conditions or browser setup.

```mokr scrape [-h] [--type] [--headful] [--timeout] [--wait-until] [--user-agent] [--proxy] [--output-file] url```

Positional arguments:
  - url: Target URL to scrape.

Options:
  - `--type`: Either "chrome" or "firefox".
  - `--headful`: Run in headful (not headless) browser.
  - `--timeout`: Time in milliseconds to wait for page to load.
  - `--wait-until`: Wait until a specific lifecycle event occurs.
  - `--user-agent`: User agent to override the page with.
  - `--proxy`: Remote proxy to use.
  - `--output-file`: Dump HTML content to given file.
