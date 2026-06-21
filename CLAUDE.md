# Project rules for Claude

## Companion app (`CompanionApp/`)

**Every change to any file in `CompanionApp/` requires bumping the service worker cache version.**

- File: `CompanionApp/sw.js`
- Variable: `const CACHE = "tremor-recorder-vN";`
- Increment `N` by 1 on every commit that touches any file in `CompanionApp/`
- Also update the version constant in `tremor_recorder.html`: `const APP_VERSION = "v0.1-alpha.N";`
- Reason: the service worker serves files from cache; without a new cache name the browser
  serves stale files and changes never reach the user.
