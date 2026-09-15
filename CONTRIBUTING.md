# Contributing to TobiiEyeTrackerTool

This document defines how changes move from an issue to a release in
`Hasan-Smajlovic/TobiiEyeTrackerTool`. The workflow and initial repository
protections are tracked in [issue #14](https://github.com/Hasan-Smajlovic/TobiiEyeTrackerTool/issues/14).
CI checks and Windows release automation are tracked separately in
[issue #16](https://github.com/Hasan-Smajlovic/TobiiEyeTrackerTool/issues/16).

## Long-lived branches

- `development` is the default branch and the integration branch for normal work.
- `master` contains release history and urgent hotfixes only.
- Do not develop directly on either long-lived branch.
- Every change to `development` or `master` must go through a pull request.
- Direct pushes, force-pushes, and deletion are blocked on both long-lived branches.

## Topic branches

Start every normal topic branch from the latest `development` branch. Use one of
these names:

- `feat/<issue>-<short-description>`
- `fix/<issue>-<short-description>`
- `docs/<issue>-<short-description>`
- `refactor/<issue>-<short-description>`
- `test/<issue>-<short-description>`
- `build/<issue>-<short-description>`
- `ci/<issue>-<short-description>`
- `chore/<issue>-<short-description>`

Use lowercase words separated by hyphens after the issue number. One branch and
one pull request should represent one coherent change. Keep unrelated changes in
separate pull requests.

For example:

```text
docs/14-development-workflow
```

## Pull request destination

Before creating any normal pull request, explicitly verify all four values:

- Base repository: `Hasan-Smajlovic/TobiiEyeTrackerTool`
- Base branch: `development`
- Compare repository: the repository that contains the topic branch
- Compare branch: the topic branch

This repository is a fork. Do not rely only on GitHub's suggested destination.
Confirm the base repository and base branch before creating the pull request.
Feature, fix, documentation, refactor, test, build, CI, and chore pull requests
all target `development`.

GitHub's generic compare page may still select the upstream
`thePi314/TobiiEyeTrackerTool:master` branch as the base. This behavior was
observed after `development` became the fork's default branch, so the four values
above must always be checked manually.

## Issue linking and pull request contents

Every normal pull request must link its issue with:

```text
Closes #<issue-number>
```

Because `development` is the default branch, merging a normal pull request with
this keyword closes the linked issue.

The pull request description must include:

- A summary of the outcome
- The scoped changes
- Verification performed
- Known limitations
- Manual checks still required

Open incomplete work as a draft pull request. Mark it ready for review only when
the described verification is complete.

## Commit and pull request titles

Use Conventional Commit-style titles:

- `feat(scope): description`
- `fix(scope): description`
- `docs(scope): description`
- `refactor(scope): description`
- `test(scope): description`
- `build(scope): description`
- `ci(scope): description`
- `chore(scope): description`

When a normal pull request is squash-merged into `development`, its title becomes
the squash commit title and its description becomes the squash commit body.
Feature-branch work-in-progress commits may be imperfect because they are
squashed, but they must remain understandable and must never contain secrets.

## Review and merge responsibility

- One approving review from a collaborator with write permission is required.
- A pull request author cannot approve their own pull request.
- Hasan reviews Tajib's pull requests.
- Tajib reviews Hasan's pull requests.
- New commits dismiss previous approvals. The latest diff must be approved again.
- Every review conversation must be resolved before merge.
- Hasan, Tajib, and Ali may perform the final merge into `development` or
  `master` after all applicable quality rules are satisfied.
- An approval means the reviewer accepts the implementation and the reported
  verification. It does not replace CI or required Windows and Tobii hardware
  checks.

There is no active maintainer-only update restriction. Collaborators with write
or administrator permission may merge, but the independent pull request quality
rulesets apply to everyone and have no bypass actors.

## Merge strategy

- Normal topic branch to `development`: squash merge only.
- `development` to `master`: merge commit only.
- Hotfix branch to `master`: merge commit only.
- Delete a merged topic branch after a successful merge.
- Never delete `development` or `master`.
- Do not use rebase merge.
- Do not use auto-merge or a merge queue under the issue #14 workflow.

Release merges use merge commits so `development` remains an ancestor of
`master`. This keeps later release pull requests clean and prevents already
released commits from appearing again.

## Release process

1. Confirm that all intended changes have already been merged into `development`.
2. Decide the next Semantic Versioning number and write it without the `v` prefix
   in `VERSION` as part of the release pull request.
3. Until the project declares a stable public version, use `v0.MINOR.PATCH`,
   starting with `v0.1.0` unless Hasan selects another initial version.
4. Open a release pull request from `development` to `master`.
5. Summarize the included changes, identify the version, link relevant issues and
   pull requests, list verification, and document known limitations.
6. Obtain one approval and resolve every review conversation.
7. Hasan merges the release pull request with a merge commit.
8. The release workflow builds the exact merged `master` commit and creates the
   immutable version tag, release artifact, release notes, and checksum.
9. A failed release workflow must not create a partial or duplicate release.
   Rerun the failed workflow for the same commit. If the version tag belongs to a
   different commit, bump `VERSION` in a new reviewed pull request.

Do not create a version tag or GitHub Release as part of issue #14.

## Hotfix process

1. Create `hotfix/<issue>-<short-description>` from `master`.
2. Write the next unused patch version to `VERSION` in the hotfix branch.
3. Open a reviewed pull request from the hotfix branch to `master`.
4. Obtain one approval, resolve every review conversation, and let Hasan merge it
   with a merge commit.
5. The release workflow publishes the patch release from that exact merge commit.
6. Identify the actual hotfix commit inside the merged hotfix branch, not the merge
   commit.
7. Create `backport/<issue>-<short-description>` from the latest `development`.
8. Cherry-pick the actual hotfix commit onto the backport branch.
9. Open a normal reviewed pull request from the backport branch to `development`
   and squash-merge it.

This process prevents unfinished development work from entering an urgent release
while ensuring the fix remains part of future releases.

## Repository protection

The active `Protect development` ruleset targets only `development` and has no
bypass actors. It enforces:

- Restricted deletions
- Blocked force-pushes
- Linear history
- A pull request before merging
- One approving review
- Dismissal of stale approvals when new commits are pushed
- Resolution of all review conversations
- Squash as the only allowed merge method
- GitHub's secure default requiring an extra human approval for unattributed
  Copilot changes

It does not require Code Owner review, approval of the most recent reviewable push,
signed commits, deployments, or status checks. It does not restrict branch
creation or contain a separate update restriction.

The active `Protect master releases` ruleset targets only `master` and has no
bypass actors. It enforces:

- Restricted deletions
- Blocked force-pushes
- A pull request before merging
- One approving review
- Dismissal of stale approvals when new commits are pushed
- Resolution of all review conversations
- Merge commit as the only allowed merge method
- GitHub's secure default requiring an extra human approval for unattributed
  Copilot changes

It does not require linear history, Code Owner review, approval of the most recent
reviewable push, signed commits, deployments, or status checks. It does not
restrict branch creation or contain a separate update restriction.

The former `Maintainer merge control` ruleset is disabled and has no effect on
either branch. This allows collaborators with write or administrator permission
to merge after the applicable quality rules are satisfied. The two active quality
rulesets have no bypass actors.

## CI and required checks

Pull requests targeting `development` or `master` run these stable checks:

- `code-quality`: Ruff lint and format checks, Python bytecode compilation,
  PowerShell parsing, and focused PSScriptAnalyzer rules.
- `tests`: the hardware-independent pytest suite with the Qt offscreen backend
  and enforced coverage floor.
- `windows-package`: a clean Windows x64 PyInstaller build and packaged executable
  smoke test.

Both branch rulesets must require all three names after each check has completed
successfully at least once. The release workflow repeats the checks after a merge
to `master`; it is not a pull request check and must not be selected as a required
status check.

Release automation creates tags and GitHub Releases from the exact merged
`master` commit without pushing directly to `master`. It therefore does not need
a protected-branch bypass. The full packaging and recovery procedure is in
[`docs/WINDOWS_RELEASE.md`](docs/WINDOWS_RELEASE.md).
Local commands and the UI review checklist are in
[`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

## GitHub plan limitations

The personal account currently shows the GitHub Pro plan. The repository is public
and user-owned.

- Branch and tag rulesets are available for public repositories on GitHub Free and
  paid plans.
- Organization teams and required team reviewers are unavailable in a user-owned
  repository.
- Required status checks cannot be selected reliably until issue #16 creates the
  workflows and they produce stable passing check names.
- Push rulesets for restricting paths, extensions, or file sizes are outside issue
  #14 and must not be added as part of this workflow configuration.
- No active ruleset limits final merges to one person. GitHub allows collaborators
  with write or administrator permission to merge after the applicable quality
  rules are satisfied. The current eligible collaborators are Hasan, Tajib, and
  Ali.

## Exceptions and break-glass recovery

Do not add a bypass for maintainers, the write role, GitHub Actions, Dependabot,
Codex, Copilot, or any other automation to either pull request quality ruleset.
The repository owner is the break-glass recovery operator.

If a rule blocks an urgent recovery:

1. Hasan records the reason, affected commit, and intended correction before the
   recovery.
2. Temporarily disable only the ruleset that blocks the required recovery.
3. Perform the smallest possible corrective action.
4. Immediately restore the ruleset and verify its active configuration.
5. Open a follow-up issue or pull request documenting what happened and how a
   recurrence will be prevented.

Never use force-push as the routine recovery method.
