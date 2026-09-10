### What this stage is for

Writing the software down before writing it. The output is a plan file, not a chat message.

### How to behave

Cover, at minimum: routes and page inventory; the data model and where state actually lives; auth
and roles; every third-party surface and what happens when each one is DOWN; the deploy topology;
environments and secrets; and what is explicitly out of scope for v1.

The out-of-scope list is the part that gets skipped and the part that saves the project. Write it.

Then slice it. A slice is a piece that fits one session and ends in something verifiable - not "the
frontend", but "the route renders with real data and its error state is exercised".

### Gate

The plan exists, the operator has read it, and the slices each have a verifiable exit.
