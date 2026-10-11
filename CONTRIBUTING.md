# Contributing to Pogled Assist

This document defines how changes move from an issue to a release in
`Hasan-Smajlovic/Pogled-Assist`.

## Long-lived branches

- `development` is the integration branch for normal work. Check GitHub for the
  current default branch; that setting can differ from the integration branch.
  GitHub reported `master` as the default on 23 September 2026.
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

- Base repository: `Hasan-Smajlovic/Pogled-Assist`
- Base branch: `development`
- Compare repository: the repository that contains the topic branch
- Compare branch: the topic branch

This repository is a fork. Do not rely only on GitHub's suggested destination.
Confirm the base repository and base branch before creating the pull request.
Feature, fix, documentation, refactor, test, build, CI, and chore pull requests
all target `development`.

GitHub's generic compare page may select the upstream
`thePi314/TobiiEyeTrackerTool:master` branch as the base. Check all four values
manually, regardless of the current default-branch setting.

## Writing issues for coding agents

Use the closest template under `.github/ISSUE_TEMPLATE`. The issue is the handoff
to a fresh coding agent, so it must stand on its own without chat history or old
prompts. Include only information that changes how the work should be done:

- the problem or outcome;
- the files, prior work, decisions, and dependencies that provide context;
- what is in and out of scope;
- existing behavior and user data that must remain compatible;
- acceptance criteria that can be observed or tested; and
- the required automated, Windows, Tobii, and visible checks.

Link to the owning guide instead of copying setup, architecture, workflow, or
release instructions into the issue. Mark unresolved product decisions clearly;
an agent must ask before choosing an answer that changes user behavior. Remove
unused placeholders before submitting. A short, complete issue is better than a
filled template with guesses or repeated text.

If work can change behavior already used by the installed application, name the
flows that must remain compatible. Do not combine an unrelated refactor or
folder reorganization with a feature, fix, or documentation issue.

Use the project status to show whether an agent can act on the issue:

| Status | Meaning |
| --- | --- |
| Backlog | A decision, dependency, or missing requirement still blocks work. |
| Ready | The issue is self-contained and has no unresolved blocking decision. |
| In progress | An agent is actively working on the issue and its topic branch. |
| In review | The implementation and stated checks are ready for pull request review. |
| Done | The issue is closed after merge or an agreed non-code outcome. |

## Issue linking and pull request contents

Every normal pull request must reference its issue. Check the current default
branch with `gh repo view Hasan-Smajlovic/Pogled-Assist --json defaultBranchRef`
before choosing the reference. When `development` is the default branch, use:

```text
Closes #<issue-number>
```

When another branch is the default, use `Refs #<issue-number>` in a normal pull
request to `development`. GitHub does not apply closing keywords in pull requests
to a non-default branch ([GitHub's issue-linking rules](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue)).
Close the issue explicitly when the agreed work is
complete, or use a closing reference in a later pull request to the default
branch. Do not change the normal pull request destination just to close an issue.

The pull request describes the resulting diff, not the original plan. Use the
repository template in `.github/pull_request_template.md` to record the outcome,
material changes, compatibility impact, checks that actually ran, visible
evidence when relevant, and anything that remains unverified. Link to the issue
for scope, dependencies, and acceptance criteria instead of repeating them.
These branch, title, issue-linking, and template rules also apply when suggesting
a branch name, commit title, or pull request description. Read the template
before drafting pull request text, retain every heading and checklist item, and
flag any unknown issue number or verification result in suggestions. Resolve
issue references before opening the pull request, and mark skipped checks
Not run with a reason.

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
The repository has no `CHANGELOG.md`. The release workflow generates each
release's notes from merged pull request titles, so a title is also the
changelog entry users read.
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
- `release/v<version>` to `master`: merge commit only.
- Hotfix branch to `master`: merge commit only.
- Delete a merged topic branch after a successful merge.
- Never delete `development` or `master`.
- Do not use rebase merge.
- Do not use auto-merge or a merge queue.

The release branch starts at the latest `master` and merges `development`
into it. The final release PR also uses a merge commit, so `development`
remains an ancestor of `master`. The release branch can contain merge commits;
`development` stays linear.

## Release process

1. Confirm that all intended changes have already been merged into `development`.
2. Choose a Semantic Versioning increase: `patch`, `minor`, or `major`.
   The workflow calculates the new number from `master`'s `VERSION`. A minor
   increase resets patch to zero; a major increase resets both minor and patch
   to zero. Major increases are allowed, including from `0.x` to `1.0.0`.
   The version tag must not already exist.
3. On GitHub, run **Actions > Prepare release > Run workflow** from `master`
   and select the increase; the default is `patch`. The workflow creates
   `release/v<version>`, merges `development` into it, commits the new `VERSION`,
   and opens a draft pull request to `master`. It runs preparation code from the
   exact dispatched `master` commit and refuses to prepare if `master` has moved.
   It never updates either protected branch. If it stops after pushing the
   branch, rerun that workflow run to open the missing PR. A stale branch or a
   changed `master` requires review before starting a new preparation run.
4. Review and complete the draft PR: summarize the changes, link relevant
   issues and pull requests, list verification, and document known limitations.
   The automated text marks manual checks Not run until their results are added.
5. Approve the PR's CI run if GitHub requests it, then mark the PR ready for
   review after the required checks and applicable manual validation.
6. Obtain one independent approval and resolve every review conversation.
7. Hasan merges the release pull request with a merge commit.
8. **Publish release** builds the exact merged `master` commit and creates the
   immutable version tag, release artifact, release notes, and checksum.
9. A failed publication workflow must not create a partial or duplicate release.
   Rerun the failed workflow for the same commit. If the version tag belongs to a
   different commit, bump `VERSION` in a new reviewed pull request.

The **Prepare release** workflow must first reach the default `master` branch
before GitHub can show its **Run workflow** button. For the first release using this
process, prepare a release branch from the latest `master` manually, merge
`development` into that branch, commit the new `VERSION`, and open a reviewed
PR to `master`. Do not use **Update branch** on a direct
`development`-to-`master` PR: it tries to add a merge commit to the protected
linear `development` branch.

If `master` still has the older **Release** workflow with a version input, use
it once to prepare the release that introduces these workflow changes. After
that release merges, use **Prepare release** with the increase selector.

The repository owner must enable **Settings > Actions > General > Allow GitHub
Actions to create and approve pull requests** for the preparation workflow's
`GITHUB_TOKEN` to open the draft. That setting does not let the workflow
approve its own PR. A PR opened by `GITHUB_TOKEN` may show **Approve workflows
to run** before CI starts. Keep the independent review and required checks.

## Hotfix process

1. Create `hotfix/<issue>-<short-description>` from `master`.
2. Write the next unused patch version to `VERSION` in the hotfix branch.
3. Open a reviewed pull request from the hotfix branch to `master`.
4. Obtain one approval, resolve every review conversation, and let Hasan merge it
   with a merge commit.
5. **Publish release** publishes the patch release from that exact merge commit.
6. Identify the actual hotfix commit inside the merged hotfix branch, not the merge
   commit.
7. Create `backport/<issue>-<short-description>` from the latest `development`.
8. Cherry-pick the actual hotfix commit onto the backport branch.
9. Open a normal reviewed pull request from the backport branch to `development`
   and squash-merge it.

This process prevents unfinished development work from entering an urgent release
while ensuring the fix remains part of future releases.

## Repository protection

The active `Protect development` and `Protect master releases` rulesets each
target only their named branch. Both block deletion and force-pushes and require
a pull request, one approving review, dismissal of stale approvals after new
commits, resolved review conversations, and successful `code-quality`, `tests`,
and `windows-package` checks on an up-to-date branch. GitHub's secure default
also requires an extra human approval for unattributed Copilot changes.

| Branch | History and allowed merge method |
| --- | --- |
| `development` | Linear history; squash merge only |
| `master` | Merge commit only; linear history is not required |

Neither ruleset has bypass actors or requires Code Owner review, approval of the
most recent reviewable push, signed commits, or deployments. Neither restricts
branch creation or has a separate update restriction. The former `Maintainer
merge control` ruleset is disabled, so collaborators with write or administrator
permission may merge after the active rules are satisfied.

## CI and required checks

Pull requests targeting `development` or `master` run these checks:

- `dependency-review`: known vulnerabilities introduced by dependency changes;
  moderate, high, and critical findings fail the job for runtime, development,
  and unknown dependency scopes. This job runs only on pull request events.
- `code-quality`: Ruff lint and format checks, Python bytecode compilation,
  PowerShell parsing, and focused PSScriptAnalyzer rules.
- `tests`: the hardware-independent pytest suite with the Qt offscreen backend
  and enforced coverage floor.
- `windows-package`: a clean Windows x64 PyInstaller build and packaged executable
  and isolated installer smoke tests.

The active branch rulesets, checked on 23 September 2026, require
`code-quality`, `tests`, and `windows-package`. Verify the live rulesets before
relying on this list. `dependency-review` is an additional CI check; Hasan decides
whether to add it to the required checks after its first successful run.
**Publish release** repeats the software and packaging checks after a merge to
`master`; it is not a pull request check and must not be selected as a required
status check.

Dependency review requires the GitHub dependency graph. A repository administrator
must enable the dependency graph and Dependabot alerts in the repository's
security settings, or run this command with an administrator account:

```text
gh api --method PUT repos/Hasan-Smajlovic/Pogled-Assist/vulnerability-alerts
```

Alerts cover known vulnerabilities discovered in existing dependencies after a
pull request has merged. They do not require a separate repository workflow.
Enabling alerts does not enable automatic update PRs.

Release automation creates tags and GitHub Releases from the exact merged
`master` commit without pushing directly to `master`. It therefore does not need
a protected-branch bypass. The full packaging and recovery procedure is in
[`docs/WINDOWS_RELEASE.md`](docs/WINDOWS_RELEASE.md).
Local commands and the UI review checklist are in
[`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

### UI gallery publication

The **UI gallery** workflow updates one `github-actions[bot]` comment per PR.
When CI is requested or starts, it refreshes an existing gallery comment to show
that new previews are being prepared, keeping the previous images available.
The `in_progress` event also covers CI reruns, which do not emit `requested`.
After CI completes, including failed runs that produced screenshots, the workflow
publishes a GitHub Pages site with both available resolutions and refreshes the
same comment. It includes up to six main screenshots in a collapsible section,
links to the full gallery and ZIP artifact, and the rendered commit and CI result.
The status header shows the last update time in UTC, the latest PR commit, the
latest matching CI run, and whether the images match that commit and CI attempt.
Images are synthetic previews without hardware validation.

A failed gallery build or Pages deployment updates the existing comment with a
publication-failure status and a link to the gallery workflow, preserving previous
previews. A failed PR CI run is reported separately and can still have a gallery.
Start notifications cannot overwrite a completed publication's status; events
for an older PR commit or CI attempt cannot update the current comment. Status
changes do not create a comment before the first gallery is available. Repeating
the same status does not change its timestamp or create another comment.

The workflow rebuilds the site from available `ui-gallery` artifacts for all
open PRs targeting `development` or `master`. Each artifact has a distinct URL,
so reruns cannot show a cached image from an older artifact. If a new commit has
not produced screenshots, an earlier commit still in that PR can remain visible
with an explicit label. A rerun cannot reuse screenshots uploaded before its
current attempt started. Closed PRs and expired artifacts are removed on the next
publication. Run **UI gallery** manually from the default branch to refresh the
site without a new CI run. A removed or expired gallery comment is updated when
that PR is still open; the workflow does not create empty gallery comments.

The workflow and its script must first reach the default branch, currently
`master`. A merge into `development` alone does not activate publication, and
the PR introducing the workflow will not receive its gallery comment until
activation. Until then, review the `ui-gallery` ZIP artifact in the PR's CI run.
Before the first publication, Hasan or another repository administrator
must select **Settings > Pages > Build and deployment > Source > GitHub Actions**.
The `github-pages` environment must allow deployments from the default branch.
If Pages is already configured for another site, review that use before selecting
this gallery as the repository's Pages site. No PAT or extra secret is required.

The jobs `build-ui-gallery`, `publish-ui-gallery`, and `comment-ui-gallery` run
in a separate workflow; the comment job also runs at CI start and after a failed
build or deployment. They are not required PR checks and must not be
added to the branch rulesets. A Pages or comment failure does not replace or
bypass any software, packaging, or human review requirement. After setup or a
failed deployment, run **UI gallery** manually from the default branch to publish
the still-available artifacts and update PR comments without a new CI run.

Progress updates use a separate per-branch concurrency group so they cannot
displace a queued Pages publication. Pages builds and deployments remain
serialized across PRs.

PR CI keeps its read-only token. The gallery build checks out the trusted workflow
revision, reads artifact data, and rebuilds its own HTML; it never checks out or
executes PR code. ZIP path, file type, size, PNG header, and chunk checksum checks
reject unsafe images, and PNG text metadata is removed. Only the deployment job
can write Pages and request an OIDC token; only the comment job can write PR
comments. Neither job can push repository contents. The local Actions check
validates every YAML workflow under `.github/workflows/`.

## GitHub plan limitations

The personal account currently shows the GitHub Pro plan. The repository is public
and user-owned.

- Branch and tag rulesets are available for public repositories on GitHub Free and
  paid plans.
- Organization teams and required team reviewers are unavailable in a user-owned
  repository.
- Push rulesets for restricting paths, extensions, or file sizes are not part of
  the current workflow configuration.
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
