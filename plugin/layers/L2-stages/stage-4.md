### What this stage is for

The difference between a demo and software. This is where it is earned.

### How to behave

Walk the paths a demo never walks: the empty state, the error, the slow network, the second click,
the expired session, the malformed input, the 404 and the 500. Then the operational ones: security
headers, rate limiting on anything public, and logging that tells you something broke before the
operator finds it.

Any one of these means it is not done - mock data on a reachable path, a stub or TODO in a shipped
path, validation only on the client, a secret reachable from the bundle, or a feature with no way to
tell in production whether it is working right now.

### Gate

That list is clean, and there is a rollback path for a bad deploy.
