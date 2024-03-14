# Firefox Considerations

Currently, Firefox is supported in a partial capacity.
Unsupported methods will raise a `mokr.exceptions.FirefoxNotImplementedError`
if called.

This is because the Chrome Devtools Protocol (CDP) is only partially, experimentally,
implemented in Firefox. Mozilla has abandoned this effort, too, to concentrate on
fully implementing [BiDi](https://developer.chrome.com/blog/webdriver-bidi).

Mozilla has [a published list of supported CDP methods](https://docs.google.com/spreadsheets/d/e/2PACX-1vRqKh563C0b0pnJruf85REpviTERnEoNEITEH3v9RvSCpkLzu9vw8c8_PAIgJoUpnUviVHV93u4V8V_/pubhtml?gid=108099026&single=true
), however it isn't very descriptive as two methods can have the same classification of "experimental"
but not be functional (such as `"Input.insertText"` which works and `"Page.addBinding"` that doesn't).

There are a few options to continue development in a meaningful way:
* As [puppeteer is tracking](https://puppeteer.github.io/ispuppeteerwebdriverbidiready/) their own progress, we could wait for this
to be closer to parity and port it.
* Port off the implementation Microsoft has done, since [they will not be abandoning their custom Firefox distribution for BiDi anytime soon](https://github.com/microsoft/playwright/pull/24073#issuecomment-1636205254). This would create an abtract dependency, though.
* A third option would be to use temporary extensions to mimic as much behaviour as possible. We could already potentially use the
[webRequest API](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/webRequest) to intercept, abort, and alert requests.
Though the `"Runtime.addBinding"` CDP method is not implemented in Firefox so it can be difficult to callback to Python methods
in a blocking manner.

## Notable Gaps

### Request Interception

Request interception is "always on" but also not blocking. Requests and responses can be observed
but will complete async and cannot be affected. 

The request interception callback chain will still be honoured, but should omit `Request.release()`,
`Request.fulfill()`, and `Request.abort()` as they will raise `FirefoxNotImplementedError`.

### Response Body

Since Firefox doesn't support `"Fetch.getResponseBody"`, the response body cannot be accessed.
This affects `Response.buffer()`, `Response.content()`, `Response.json()`, and `Response.to_dict()`.

This is not applicable for `FetchDomain` requests (`Page.fetch`).

### Disabling JavaScript

JavaScript will be enabled by default, so `Page.evaluate` and `Page.evaluate_handle` remain
functional. Unfortunately, since `"Emulation.setScriptExecutionDisabled"` is not supported,
`Page.set_javascript_enabled` is not supported.

### Dialogs

Firefox doesn't support `"handleJavaScriptDialog"` so the `Dialog` class is useless;
the raw dialog (dictionary) event will be emitted instead.

### Bound JavaScript Methods

Firefox doesn't support `"Runtime.addBinding"` (it is listed as experimental but will
hang forever), so `Page.expose_function` is not usable.

Notably, Firefox does support `"Page.addScriptToEvaluateOnNewDocument"`, so JavaScript
files could be attached for new document initialisation still.

### Screenshot Backgrounds

Screenshots are supported of both element and pages, however, Firefox doesn't support
`"setDefaultBackgroundColorOverride"`so the `omit_background` flag will be ignored
in `Page.screenshot` and `ElementHandle.screenshot`.

### Others

The below are other CDP methods Firefox doesn't support and their affected `mokr` methods.

|CDP Method | mokr Method(s) |
|---|---|
|`"DOM.setFileInputFiles"` | `ElementHandle.upload_file`|
|`"Emulation.setEmulatedMedia"` | `Page.emulate_media`|
|`"Input.dispatchTouchEvent"` | `Page.tap` and `ElementHandle.tap`|
|`"setBypassCSP"` | `Page.set_bypass_csp`|
|`"Performance.getMetrics"` |`Page.metrics`|
|`"Performance.queryObjects"` | `Page.query_objects`|