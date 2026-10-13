# UI gallery publication

This guide owns gallery status, publication setup, permissions, and recovery.
For design references, local rendering, and manual application checks, use the
[UI development guide](UI_DEVELOPMENT.md#ui-review). The
[contributing guide](../CONTRIBUTING.md#ci-and-required-checks) owns required CI checks.

## Status and freshness

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

## Activation and recovery

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

## Permissions and trusted artifacts

PR CI keeps its read-only token. The gallery build checks out the trusted workflow
revision, reads artifact data, and rebuilds its own HTML; it never checks out or
executes PR code. ZIP path, file type, size, PNG header, and chunk checksum checks
reject unsafe images, and PNG text metadata is removed. Only the deployment job
can write Pages and request an OIDC token; only the comment job can write PR
comments. Neither job can push repository contents. The local Actions check
validates every YAML workflow under `.github/workflows/`.
