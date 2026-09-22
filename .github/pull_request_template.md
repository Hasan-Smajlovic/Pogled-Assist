## Outcome

<!-- State what the diff now does. Do not repeat the issue description. -->

## Linked issue

<!-- Use Closes #<number> for a normal topic branch. -->

Closes #

## Changes

<!-- List the material implementation and documentation changes. -->

-

## Compatibility and risk

<!-- Name preserved flows and any data, install, update, or rollback impact. -->

## Verification

<!-- Record commands and results. Say Not run and why when a check was skipped. -->

- Automated:
- Manual Windows:
- Manual Tobii hardware:

## Evidence and limits

<!-- Link logs, artifacts, screenshots, or recordings when relevant. List any
remaining uncertainty. Write None only when there is none. -->

## Review checklist

- [ ] The diff contains only work needed for the linked issue.
- [ ] Existing user behavior is unchanged or the intended change is documented.
- [ ] New behavior has tests in the existing pytest suite where practical.
- [ ] Visible UI changes update the HTML design reference first, or this pull request explains why the reference is unaffected.
- [ ] Every row of the maintenance matrix in `AGENTS.md` that matches a changed path is updated.
- [ ] Hardware-only claims are separated from software-only verification.
- [ ] No prompt history, secrets, personal data, or generated runtime data is included.
