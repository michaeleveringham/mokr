# Firefox Considerations

Firefox is supported via BiDi protocol instead of Chrome's CDP. Feature parity is largely available, but there are a few gaps still.

## Current Gaps

- Disabling JavaScript. The BiDi specification defines
  `emulation.setScriptingEnabled`, but Firefox's current native endpoint returns `unknown command` for it.
- CSP bypass. The BiDi specification defines `browsingContext.setBypassCSP`, but Firefox's current native endpoint returns `unknown command` for it. Media
  emulation and performance metrics remain unavailable.
- Response-stage route callbacks are not exposed. Firefox accepts the
  corresponding BiDi commands but fails the intercepted browser request even
  for an unmodified continuation in the managed build.
- Transparent-background
  screenshot override.
