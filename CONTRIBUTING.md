# Contributing to Pogled Assist

This document defines how changes move from an issue to a release in `Hasan-Smajlovic/Pogled-Assist`.

## Long-lived branches

- `development` is the integration branch for normal work. Check GitHub for the current default branch; that setting can differ from the integration branch.
- `master` contains release history and urgent hotfixes only.
- Do not develop directly on either long-lived branch.
- Every change to `development` or `master` must go through a pull request.
- Direct pushes, force-pushes, and deletion are blocked on both long-lived branches.

## Topic branches

Start every normal topic branch from the latest `development` branch. Use one of these names:

- `feat/<issue>-<short-description>`
- `fix/<issue>-<short-description>`
- `docs/<issue>-<short-description>`
- `refactor/<issue>-<short-description>`
- `test/<issue>-<short-description>`
- `build/<issue>-<short-description>`
- `ci/<issue>-<short-description>`
- `chore/<issue>-<short-description>`

Use lowercase words separated by hyphens after the issue number. One branch and one pull request should represent one coherent change. Keep unrelated changes in separate pull requests.

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

This repository is a fork. Do not rely only on GitHub's suggested destination. Confirm the base repository and base branch before creating the pull request. Feature, fix, documentation, refactor, test, build, CI, and chore pull requests all target `development`.

GitHub's generic compare page may select the upstream `thePi314/TobiiEyeTrackerTool:master` branch as the base. Check all four values manually, regardless of the current default-branch setting.

## Writing issues for coding agents

Use the closest template under `.github/ISSUE_TEMPLATE`. The issue is the handoff to a fresh coding agent, so it must stand on its own without chat history or old prompts. Include only information that changes how the work should be done:

- the problem or outcome;
- the files, prior work, decisions, and dependencies that provide context;
- what is in and out of scope;
- existing behavior and user data that must remain compatible;
- observable acceptance criteria and task-specific checks under `Done when`.

Put scope and compatibility constraints in `Context` or `Details`. Include environment and hardware details only when relevant to the task.

Link to the owning guide instead of copying setup, architecture, workflow, or release instructions into the issue. Mark unresolved product decisions clearly; an agent must ask before choosing an answer that changes user behavior. Remove unused placeholders before submitting. A short, complete issue is better than a filled template with guesses or repeated text.

If work can change behavior already used by the installed application, name the flows that must remain compatible. Do not combine an unrelated refactor or folder reorganization with a feature, fix, or documentation issue.

Use the project status to show whether an agent can act on the issue:

| Status | Meaning |
| --- | --- |
| Backlog | A decision, dependency, or missing requirement still blocks work. |
| Ready | The issue is self-contained and has no unresolved blocking decision. |
| In progress | An agent is actively working on the issue and its topic branch. |
| In review | The implementation and stated checks are ready for pull request review. |
| Done | The issue is closed after merge or an agreed non-code outcome. |

## Issue linking and pull request contents

Every normal pull request must reference its issue. Check the current default branch with `gh repo view Hasan-Smajlovic/Pogled-Assist --json defaultBranchRef` before choosing the reference. When `development` is the default branch, use:

```text
Closes #<issue-number>
```

When another branch is the default, use `Refs #<issue-number>` in a normal pull request to `development`. GitHub does not apply closing keywords in pull requests to a non-default branch ([GitHub's issue-linking rules](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue)). Close the issue explicitly when the agreed work is complete, or use a closing reference in a later pull request to the default branch. Do not change the normal pull request destination just to close an issue.

Use `.github/pull_request_template.md`: put the issue reference first, describe the result and material decisions in `Outcome`, record checks and their evidence in `Verification`, and name compatibility impacts or remaining limitations in `Risks and limits`. Link to the issue for scope, dependencies, and acceptance criteria instead of repeating them. Standing requirements remain in `AGENTS.md` and the linked guides; do not copy them into a checklist. These branch, title, issue-linking, and template rules also apply when suggesting a branch name, commit title, or pull request description. Read the template before drafting pull request text, retain every heading, and flag any unknown issue number or verification result in suggestions. Resolve issue references before opening the pull request. Mark skipped checks Not run and irrelevant checks Not applicable, each with a reason. Keep software-only and hardware results separate.

Open incomplete or unverified work as a draft pull request, listing unfinished work and every skipped check as Not run with a reason. An implementation handoff or draft does not establish readiness for review. Mark the pull request ready only after the final complete check (prefer `.\dev.ps1 check -Parallel`) and applicable manual verification in the [development guide](docs/DEVELOPMENT.md#verification-before-a-pull-request) are complete. Required CI checks and human review must pass before merge.

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

When a normal pull request is squash-merged into `development`, its title becomes the squash commit title and its description becomes the squash commit body. The repository has no `CHANGELOG.md`. The release workflow generates each release's notes from merged pull request titles, so a title is also the changelog entry users read. Feature-branch work-in-progress commits may be imperfect because they are squashed, but they must remain understandable and must never contain secrets.

## Review and merge responsibility

- One approving review from a collaborator with write permission is required.
- A pull request author cannot approve their own pull request.
- Hasan reviews Tajib's pull requests.
- Tajib reviews Hasan's pull requests.
- New commits dismiss previous approvals. The latest diff must be approved again.
- Every review conversation must be resolved before merge.
- Hasan, Tajib, and Ali may perform the final merge into `development` or `master` after all applicable quality rules are satisfied.
- An approval means the reviewer accepts the implementation and the reported verification. It does not replace CI or required Windows and Tobii hardware checks.

There is no active maintainer-only update restriction. Collaborators with write or administrator permission may merge, but the independent pull request quality rulesets apply to everyone and have no bypass actors.

## Merge strategy

- Normal topic branch to `development`: squash merge only.
- `release/v<version>` to `master`: merge commit only.
- Hotfix branch to `master`: merge commit only.
- Delete a merged topic branch after a successful merge.
- Never delete `development` or `master`.
- Do not use rebase merge.
- Do not use auto-merge or a merge queue.

The release branch starts at the latest `master` and merges `development` into it. The final release PR also uses a merge commit, so `development` remains an ancestor of `master`. The release branch can contain merge commits; `development` stays linear.

## Release process

1. Confirm that all intended changes have already been merged into `development`.
2. Choose a Semantic Versioning increase: `patch`, `minor`, or `major`. The workflow calculates the new number from `master`'s `VERSION`. A minor increase resets patch to zero; a major increase resets both minor and patch to zero. Major increases are allowed, including from `0.x` to `1.0.0`. The version tag must not already exist.
3. On GitHub, run **Actions > Prepare release > Run workflow** from `master` and select the increase; the default is `patch`. The workflow creates `release/v<version>`, merges `development` into it, commits the new `VERSION`, and opens a draft pull request to `master`. It runs preparation code from the exact dispatched `master` commit and refuses to prepare if `master` has moved. It never updates either protected branch. If it stops after pushing the branch, rerun that workflow run to open the missing PR. A stale branch or a changed `master` requires review before starting a new preparation run.
4. Review and complete the draft PR: summarize the changes, link relevant issues and pull requests, list verification, and document known limitations. The automated text marks manual checks Not run until their results are added.
5. Approve the PR's CI run if GitHub requests it, then mark the PR ready for review after the required checks and applicable manual validation.
6. Obtain one independent approval and resolve every review conversation.
7. Hasan merges the release pull request with a merge commit.
8. **Publish release** builds the exact merged `master` commit and creates the immutable version tag, release artifact, release notes, and checksum.
9. A failed publication workflow must not create a partial or duplicate release. Rerun the failed workflow for the same commit. If the version tag belongs to a different commit, bump `VERSION` in a new reviewed pull request.

Do not use **Update branch** on a direct `development`-to-`master` PR: it tries to add a merge commit to the protected linear `development` branch.

The repository owner must enable **Settings > Actions > General > Allow GitHub Actions to create and approve pull requests** for the preparation workflow's `GITHUB_TOKEN` to open the draft. That setting does not let the workflow approve its own PR. A PR opened by `GITHUB_TOKEN` may show **Approve workflows to run** before CI starts. Keep the independent review and required checks.

## Hotfix process

1. Create `hotfix/<issue>-<short-description>` from `master`.
2. Write the next unused patch version to `VERSION` in the hotfix branch.
3. Open a reviewed pull request from the hotfix branch to `master`.
4. Obtain one approval, resolve every review conversation, and let Hasan merge it with a merge commit.
5. **Publish release** publishes the patch release from that exact merge commit.
6. **Sync hotfix to development** prepares `sync/<hotfix-PR-number>` from `development`, backports the released hotfix excluding the root `VERSION` file and opens a draft PR to `development`. Development keeps its existing version; master owns release versions. VERSION-only hotfixes do not open empty PRs. It reuses an existing open draft and skips changes already present. Runs for the same hotfix PR are serialized; different hotfixes have separate concurrency groups so they cannot replace each other's pending runs. This runs independently of release publication; a failed release still needs repair.
7. Review the backport, complete required checks, and squash-merge manually. The short-lived head can be updated from development without writing development changes to master. A conflict outside the root `VERSION` file leaves nothing pushed and reports manual recovery instructions in the workflow summary.

The workflow must first reach master. Enable **Allow GitHub Actions to create and approve pull requests**, as for release preparation. A PR created with `GITHUB_TOKEN` may require workflow approval before CI runs. The workflow's `sync-hotfix-pr` job has contents and pull-request write permissions only for the isolated backport. It executes inline trusted code, never checked-out scripts or hooks. It accepts only merged `hotfix/` PRs from the same repository targeting master. It never pushes master/development, force-pushes, approves or auto-merges. Command failures appear in logs and the step summary with credentials redacted. If draft creation fails after a push, a rerun reuses an identical backport branch. A branch with different content is left unchanged for manual review.

This process prevents unfinished development work from entering an urgent release while ensuring the fix remains part of future releases.

## Repository protection

Repository policy uses `Protect development` and `Protect master releases`, each targeting its named branch. Verify the live GitHub configuration before relying on enforcement. Both block deletion and force-pushes and require a pull request, one approving review, dismissal of stale approvals after new commits, resolved review conversations, and successful `code-quality`, `tests`, and `windows-package` checks on an up-to-date branch. GitHub's secure default also requires an extra human approval for unattributed Copilot changes.

| Branch | History and allowed merge method |
| --- | --- |
| `development` | Linear history; squash merge only |
| `master` | Merge commit only; linear history is not required |

Neither ruleset has bypass actors or requires Code Owner review, approval of the most recent reviewable push, signed commits, or deployments. Neither restricts branch creation or has a separate update restriction. Collaborators with write or administrator permission may merge after the active rules are satisfied.

## CI and required checks

Pull requests targeting `development` or `master` run these checks:

- `dependency-review`: known vulnerabilities introduced by dependency changes; moderate, high, and critical findings fail the job for runtime, development, and unknown dependency scopes. This job runs only on pull request events.
- `code-quality`: Ruff lint and format checks, Python bytecode compilation, PowerShell parsing, and focused PSScriptAnalyzer rules.
- `tests`: the hardware-independent pytest suite with the Qt offscreen backend and enforced coverage floor.
- `windows-package`: a clean Windows x64 PyInstaller build and packaged executable and isolated installer smoke tests.

The required checks under this policy are `code-quality`, `tests`, and `windows-package`. Verify the live rulesets before relying on this list. `dependency-review` is an additional CI check; Hasan decides whether to add it to the required checks after its first successful run. **Publish release** repeats the software and packaging checks after a merge to `master`; it is not a pull request check and must not be selected as a required status check.

Dependency review requires the GitHub dependency graph. A repository administrator must enable the dependency graph and Dependabot alerts in the repository's security settings, or run this command with an administrator account:

```text
gh api --method PUT repos/Hasan-Smajlovic/Pogled-Assist/vulnerability-alerts
```

Alerts cover known vulnerabilities discovered in existing dependencies after a pull request has merged. They do not require a separate repository workflow. Enabling alerts does not enable automatic update PRs.

Release automation creates tags and GitHub Releases from the exact merged `master` commit without pushing directly to `master`. It therefore does not need a protected-branch bypass. The full packaging and recovery procedure is in [`docs/WINDOWS_RELEASE.md`](docs/WINDOWS_RELEASE.md). Local commands and automated verification are in the [development guide](docs/DEVELOPMENT.md); the [UI development guide](docs/UI_DEVELOPMENT.md#ui-review) owns visual review and manual Windows/Tobii checks.

### UI gallery publication

PR CI produces UI screenshots, and a separate workflow publishes the gallery and maintains its PR comment. Setup, artifact handling, permissions, and failure recovery are maintained in the [UI gallery guide](docs/UI_GALLERY.md). The gallery jobs are not required PR checks and do not replace human UI review.

## Exceptions and break-glass recovery

Do not add a bypass for maintainers, the write role, GitHub Actions, Dependabot, Codex, Copilot, or any other automation to either pull request quality ruleset. The repository owner is the break-glass recovery operator.

If a rule blocks an urgent recovery:

1. Hasan records the reason, affected commit, and intended correction before the recovery.
2. Temporarily disable only the ruleset that blocks the required recovery.
3. Perform the smallest possible corrective action.
4. Immediately restore the ruleset and verify its active configuration.
5. Open a follow-up issue or pull request documenting what happened and how a recurrence will be prevented.

Never use force-push as the routine recovery method.
