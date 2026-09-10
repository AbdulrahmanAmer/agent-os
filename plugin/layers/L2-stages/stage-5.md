### What this stage is for

Shipping it, then improving it without breaking it.

### How to behave

Verify against production, not against the build. A passing build is evidence about the build; a
deploy is only good when the live thing was observed working.

Watch it after it lands. If a deploy fails its smoke check, restore service first and diagnose
second - never leave the live thing broken while you investigate.

New work re-enters at the stage it needs. A new feature starts at SHAPE for its own scope, not at
BUILD because the repository already exists.

### Gate

Verified live, watched, and the next slice chosen deliberately rather than by whatever broke.
