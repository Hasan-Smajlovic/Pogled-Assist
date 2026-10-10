from __future__ import annotations

import io
import re
import stat
import struct
import zlib
from copy import deepcopy
from datetime import datetime
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile, ZipInfo

import pytest

from scripts.ui import prepare_ui_gallery_site as site

BASE_URL = "https://example.github.io/Pogled-Assist"
FIRST_SHA = "a" * 40
SECOND_SHA = "b" * 40


def test_site_keeps_multiple_prs_and_does_not_publish_artifact_html(tmp_path):
    api = FakeGitHub()
    api.pulls.append(_pull(2, SECOND_SHA))
    api.runs[102] = _run(2, 102, SECOND_SHA)
    api.artifacts.append(_artifact(102, SECOND_SHA, 2))
    api.archives[102] = _archive({"1440x900/speech.png": _png()})
    api.pulls[0]["title"] = '<script>alert("PR title")</script>'

    comments = site.prepare_site(api, tmp_path / "site", BASE_URL)

    assert {comment["number"] for comment in comments} == {1, 2}
    for number, artifact_id in ((1, 101), (2, 102)):
        directory = tmp_path / "site" / f"pr-{number}" / f"artifact-{artifact_id}"
        assert (directory / "1440x900" / "speech.png").read_bytes() == _png()
        html = (directory / "1440x900" / "index.html").read_text(encoding="utf-8")
        assert "attacker.example" not in html
        assert "speech.png" in html
        assert "Hardware and Windows input are disabled" in html
    root = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert '<script>alert("PR title")</script>' not in root
    assert "&lt;script&gt;" in root
    assert api.writes == []
    assert comments[0]["body"].startswith(site.COMMENT_MARKER)
    assert f"{BASE_URL}/pr-1/artifact-101/1440x900/speech.png" in comments[0]["body"]


def test_newest_gallery_wins_and_reruns_have_a_new_image_url(tmp_path):
    api = FakeGitHub()
    api.runs[101]["run_attempt"] = 2
    api.artifacts.append({**_artifact(101), "id": 103})
    api.archives[103] = _archive({"1280x720/speech.png": _png(metadata=True)})

    comments = site.prepare_site(api, tmp_path / "site", BASE_URL)

    assert api.downloads == [103]
    assert "artifact-103/1280x720/speech.png" in comments[0]["body"]
    assert "/artifacts/103" in comments[0]["body"]


def test_previous_commit_gallery_is_labelled_while_new_ci_is_pending(tmp_path):
    api = FakeGitHub()
    api.pulls[0]["head"]["sha"] = SECOND_SHA
    api.commits[1] = [{"sha": FIRST_SHA}, {"sha": SECOND_SHA}]

    comments = site.prepare_site(api, tmp_path / "site", BASE_URL)

    assert comments[0]["head_sha"] == SECOND_SHA
    assert f"`{FIRST_SHA[:7]}`" in comments[0]["body"]
    assert "earlier commit" in comments[0]["body"]


def test_current_commit_gallery_wins_over_a_later_rerun_of_an_old_commit(tmp_path):
    api = FakeGitHub()
    api.pulls[0]["head"]["sha"] = SECOND_SHA
    api.runs[102] = _run(1, 102, SECOND_SHA)
    api.artifacts.append(_artifact(102, SECOND_SHA))
    api.artifacts.append({**_artifact(101), "id": 103})
    api.archives[102] = api.archives[101]
    api.archives[103] = api.archives[101]
    api.commits[1] = [{"sha": FIRST_SHA}, {"sha": SECOND_SHA}]

    comments = site.prepare_site(api, tmp_path / "site", BASE_URL)

    assert api.downloads == [102]
    assert f"`{SECOND_SHA[:7]}`" in comments[0]["body"]
    assert "earlier commit" not in comments[0]["body"]


def test_rebased_commit_is_not_published_as_a_current_pr_gallery(tmp_path):
    api = FakeGitHub()
    api.pulls[0]["head"]["sha"] = SECOND_SHA
    api.commits[1] = [{"sha": SECOND_SHA}]

    comments = site.prepare_site(api, tmp_path / "site", BASE_URL)

    assert not comments[0]["create"]
    assert api.downloads == []
    assert not (tmp_path / "site" / "pr-1").exists()


@pytest.mark.parametrize(
    "change",
    [
        {"workflow_id": 99},
        {"event": "workflow_dispatch"},
        {"status": "in_progress"},
        {"head_repository": {"id": 999}},
        {"head_repository": None},
        {"pull_requests": [{"number": 2, "base": {"ref": "development"}}]},
        {"pull_requests": [{"number": 1, "base": {"ref": "master"}}]},
    ],
)
def test_artifacts_from_an_unrelated_run_are_not_downloaded(tmp_path, change):
    api = FakeGitHub()
    api.runs[101].update(change)

    comments = site.prepare_site(api, tmp_path / "site", BASE_URL)

    assert not comments[0]["create"]
    assert api.downloads == []


def test_fork_run_with_no_pr_association_can_use_its_matching_head(tmp_path):
    api = FakeGitHub()
    api.runs[101]["pull_requests"] = []

    comments = site.prepare_site(api, tmp_path / "site", BASE_URL)

    assert comments[0]["create"]
    assert api.downloads == [101]


def test_closed_prs_and_expired_artifacts_are_removed_from_the_next_site(tmp_path):
    api = FakeGitHub()
    api.artifacts[0]["expired"] = True

    comments = site.prepare_site(api, tmp_path / "expired", BASE_URL)

    assert not comments[0]["create"]
    assert api.downloads == []
    api.pulls.clear()
    assert site.prepare_site(api, tmp_path / "closed", BASE_URL) == []
    assert not (tmp_path / "closed" / "pr-1").exists()


def test_invalid_gallery_does_not_stop_another_pr_from_being_published(tmp_path):
    api = FakeGitHub()
    api.archives[101] = b"not a ZIP"
    api.pulls.append(_pull(2, SECOND_SHA))
    api.runs[102] = _run(2, 102, SECOND_SHA)
    api.artifacts.append(_artifact(102, SECOND_SHA, 2))
    api.archives[102] = _archive({"1440x900/speech.png": _png()})

    comments = site.prepare_site(api, tmp_path / "site", BASE_URL)

    assert not comments[0]["create"]
    assert comments[1]["create"]


def test_failed_ci_still_publishes_available_images_and_reports_failure(tmp_path):
    api = FakeGitHub()
    api.runs[101]["conclusion"] = "failure"

    comments = site.prepare_site(api, tmp_path / "site", BASE_URL)

    assert comments[0]["create"]
    assert "CI: **failure**" in comments[0]["body"]


@pytest.mark.parametrize("path", ["../speech.png", "/speech.png", "1440x900\\speech.png"])
def test_archive_rejects_paths_that_could_escape_the_output(path):
    archive = _archive({path: _png()})
    with ZipFile(io.BytesIO(archive)) as zipped:
        assert zipped.infolist()[0].orig_filename == path
    with pytest.raises(ValueError, match="unsafe path"):
        site.read_images(archive)


def test_archive_rejects_symlinks_and_duplicate_images():
    link = ZipInfo("1440x900/speech.png")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    output = io.BytesIO()
    with ZipFile(output, "w") as zipped:
        zipped.writestr(link, "../../outside.png")
    with pytest.raises(ValueError, match="file type"):
        site.read_images(output.getvalue())
    with pytest.warns(UserWarning, match="Duplicate name"):
        duplicate = _archive(
            [
                ("1440x900/speech.png", _png()),
                ("1440x900/speech.png", _png()),
            ]
        )
    with pytest.raises(ValueError, match="unexpected image"):
        site.read_images(duplicate)


@pytest.mark.parametrize("case", ["html", "truncated", "trailing", "checksum"])
def test_archive_rejects_invalid_or_incomplete_png_data(case):
    images = {
        "html": b"<html>not an image</html>",
        "truncated": _png()[:-1],
        "trailing": _png() + b"<script>trailing content</script>",
        "checksum": _png()[:29] + b"xxxx" + _png()[33:],
    }
    with pytest.raises(ValueError):
        site.read_images(_archive({"1440x900/speech.png": images[case]}))


def test_png_text_metadata_is_removed_and_pixel_data_is_kept():
    images = site.read_images(_archive({"1440x900/speech.png": _png(metadata=True, gamma=True)}))

    assert images["1440x900/speech.png"] == _png(gamma=True)
    assert b"private metadata" not in images["1440x900/speech.png"]


def test_archive_and_site_size_limits_fail_before_deployment(tmp_path, monkeypatch):
    monkeypatch.setattr(site, "MAX_GALLERY_BYTES", 1)
    with pytest.raises(ValueError, match="expanded"):
        site.read_images(_archive({"1440x900/speech.png": _png()}))
    monkeypatch.setattr(site, "MAX_GALLERY_BYTES", 128 * 1024 * 1024)
    monkeypatch.setattr(site, "MAX_SITE_BYTES", 1)
    with pytest.raises(ValueError, match="site exceeds"):
        site.prepare_site(FakeGitHub(), tmp_path / "site", BASE_URL)


def test_comment_updates_only_its_own_bot_comment_without_duplicates(tmp_path):
    api = FakeGitHub()
    galleries = site.prepare_site(api, tmp_path / "site", BASE_URL)
    api.comments[1] = [
        {"id": 1, "user": {"login": "reviewer"}, "body": site.COMMENT_MARKER},
        {"id": 2, "user": {"login": "github-actions[bot]"}, "body": "Another bot report"},
        {"id": 3, "user": {"login": "github-actions[bot]"}, "body": site.COMMENT_MARKER},
    ]

    site.update_comments(api, galleries)
    site.update_comments(api, galleries)

    assert api.writes == [("PATCH", "issues/comments/3", {"body": api.comments[1][2]["body"]})]
    assert api.comments[1][0]["body"] == site.COMMENT_MARKER
    assert api.comments[1][1]["body"] == "Another bot report"


def test_comment_is_created_once_and_stale_or_closed_prs_are_skipped(tmp_path):
    api = FakeGitHub()
    galleries = site.prepare_site(api, tmp_path / "site", BASE_URL)

    site.update_comments(api, galleries)
    site.update_comments(api, galleries)

    assert len(api.writes) == 1
    assert api.writes[0][0:2] == ("POST", "issues/1/comments")
    api.pulls[0]["head"]["sha"] = SECOND_SHA
    api.comments[1].clear()
    site.update_comments(api, galleries)
    api.pulls[0]["head"]["sha"] = FIRST_SHA
    api.pulls[0]["state"] = "closed"
    site.update_comments(api, galleries)
    assert len(api.writes) == 1


def test_expired_gallery_updates_an_existing_comment_but_does_not_create_one(tmp_path):
    api = FakeGitHub()
    api.artifacts[0]["expired"] = True
    galleries = site.prepare_site(api, tmp_path / "site", BASE_URL)

    site.update_comments(api, galleries)

    assert api.writes == []
    api.comments[1] = [
        {"id": 3, "user": {"login": "github-actions[bot]"}, "body": site.COMMENT_MARKER}
    ]
    site.update_comments(api, galleries)
    assert api.writes == [("PATCH", "issues/comments/3", {"body": api.comments[1][0]["body"]})]
    assert "No UI gallery is available" in api.comments[1][0]["body"]


@pytest.mark.e2e
def test_comment_tracks_new_commit_failure_and_recovery_without_losing_previews(tmp_path):
    api = FakeGitHub()
    first = site.prepare_site(api, tmp_path / "first", BASE_URL)
    site.update_comments(api, first, publication_run_id=201)
    assert "Gallery matches the latest PR commit and CI run" in api.comments[1][0]["body"]
    assert re.search(
        r"Last updated: \*\*\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC", api.comments[1][0]["body"]
    )
    assert len(api.comments[1]) == 1

    api.pulls[0]["head"]["sha"] = SECOND_SHA
    api.commits[1] = [{"sha": FIRST_SHA}, {"sha": SECOND_SHA}]
    api.runs[102] = {**_run(1, 102, SECOND_SHA), "status": "in_progress", "conclusion": None}
    site.update_status(api, "preparing", 202, ci_run_id=102, ci_attempt=1)
    body = api.comments[1][0]["body"]
    assert "New gallery is being prepared" in body
    assert f"Latest PR commit: [`{SECOND_SHA[:7]}`]" in body
    assert "Latest CI: **in_progress**" in body
    assert f"Rendered commit: `{FIRST_SHA[:7]}`" in body
    assert "artifact-101/1440x900/speech.png" in body

    # The start notification can arrive after CI has finished but before Pages does.
    api.runs[102].update(status="completed", conclusion="success")
    site.update_status(api, "preparing", 202, ci_run_id=102, ci_attempt=1)
    assert "Waiting for gallery publication" in api.comments[1][0]["body"]
    site.update_status(api, "failed", 203, ci_run_id=102, ci_attempt=1)
    body = api.comments[1][0]["body"]
    assert "Gallery publication failed" in body
    assert "/actions/runs/203" in body
    assert "artifact-101/1440x900/speech.png" in body
    site.update_status(api, "preparing", 202, ci_run_id=102, ci_attempt=1)
    assert api.comments[1][0]["body"] == body

    api.artifacts.append(_artifact(102, SECOND_SHA))
    api.archives[102] = api.archives[101]
    second = site.prepare_site(api, tmp_path / "second", BASE_URL)
    site.update_comments(api, second, publication_run_id=204)
    body = api.comments[1][0]["body"]
    assert "Gallery matches the latest PR commit and CI run" in body
    assert f"Rendered commit: `{SECOND_SHA[:7]}`" in body
    assert "artifact-102/1440x900/speech.png" in body
    assert "artifact-101" not in body
    assert "Gallery publication failed" not in body
    assert body.count(site.STATUS_START) == 1
    assert len(api.comments[1]) == 1
    site.update_status(api, "preparing", 202, ci_run_id=102, ci_attempt=1)
    assert api.comments[1][0]["body"] == body


@pytest.mark.parametrize("status", ["queued", "in_progress"])
def test_rerun_of_same_commit_marks_existing_images_as_older(tmp_path, status):
    api = FakeGitHub()
    first = site.prepare_site(api, tmp_path / "first", BASE_URL)
    site.update_comments(api, first, publication_run_id=201)
    api.runs[101].update(status=status, conclusion=None, run_attempt=2)

    site.update_status(api, "preparing", 202, ci_run_id=101, ci_attempt=2)

    body = api.comments[1][0]["body"]
    assert "New gallery is being prepared" in body
    assert f"Latest CI: **{status}**" in body
    assert "artifact-101/1440x900/speech.png" in body
    assert "Gallery matches the latest" not in body


def test_rerun_does_not_publish_images_from_its_previous_attempt(tmp_path):
    api = FakeGitHub()
    api.runs[101].update(run_attempt=2, run_started_at="2026-10-09T08:00:00Z")

    comments = site.prepare_site(api, tmp_path / "site", BASE_URL)

    assert not comments[0]["create"]
    assert api.downloads == []


@pytest.mark.parametrize("publication", ["preparing", "failed"])
def test_old_ci_event_cannot_replace_status_for_a_newer_commit(tmp_path, publication):
    api = FakeGitHub()
    galleries = site.prepare_site(api, tmp_path / "site", BASE_URL)
    site.update_comments(api, galleries, publication_run_id=201)
    body = api.comments[1][0]["body"]
    api.pulls[0]["head"]["sha"] = SECOND_SHA
    api.runs[102] = _run(1, 102, SECOND_SHA)

    site.update_status(api, publication, 202, ci_run_id=101, ci_attempt=1)

    assert api.comments[1][0]["body"] == body
    assert len(api.writes) == 1


def test_old_rerun_event_and_unrelated_pr_do_not_get_a_status_update(tmp_path):
    api = FakeGitHub()
    galleries = site.prepare_site(api, tmp_path / "site", BASE_URL)
    site.update_comments(api, galleries, publication_run_id=201)
    api.pulls.append(_pull(2))
    api.runs[102] = _run(2, 102)
    api.comments[2] = [
        {"id": 50, "user": {"login": "github-actions[bot]"}, "body": site.COMMENT_MARKER}
    ]
    api.runs[101].update(status="in_progress", conclusion=None, run_attempt=2)

    site.update_status(api, "failed", 202, ci_run_id=101, ci_attempt=1)

    assert len(api.writes) == 1
    assert api.comments[2][0]["body"] == site.COMMENT_MARKER


def test_publication_reads_latest_ci_instead_of_reusing_build_status(tmp_path):
    api = FakeGitHub()
    galleries = site.prepare_site(api, tmp_path / "site", BASE_URL)
    api.runs[102] = {**_run(1, 102), "status": "in_progress", "conclusion": None}

    site.update_comments(api, galleries, publication_run_id=201)

    body = api.comments[1][0]["body"]
    assert "New gallery is being prepared" in body
    assert "/actions/runs/102" in body
    assert "Gallery matches the latest" not in body


@pytest.mark.parametrize("publication", ["preparing", "failed"])
def test_status_only_updates_gallery_bot_comment_and_does_not_create_one(publication):
    api = FakeGitHub()
    api.comments[1] = [
        {"id": 1, "user": {"login": "reviewer"}, "body": site.COMMENT_MARKER},
        {"id": 2, "user": {"login": "github-actions[bot]"}, "body": "Other report"},
    ]

    site.update_status(api, publication, 201, ci_run_id=101, ci_attempt=1)

    assert api.writes == []


def test_status_keeps_timestamp_when_nothing_else_changes(tmp_path, monkeypatch):
    api = FakeGitHub()
    galleries = site.prepare_site(api, tmp_path / "site", BASE_URL)
    site.update_comments(api, galleries, publication_run_id=201)
    api.runs[101].update(status="in_progress", conclusion=None, run_attempt=2)
    site.update_status(api, "preparing", 202, ci_run_id=101, ci_attempt=2)
    body = api.comments[1][0]["body"]

    class LaterClock:
        @staticmethod
        def now(_timezone):
            return datetime.fromisoformat("2030-01-01T12:00:00+00:00")

    monkeypatch.setattr(site, "datetime", LaterClock)
    site.update_status(api, "preparing", 202, ci_run_id=101, ci_attempt=2)

    assert api.comments[1][0]["body"] == body
    assert len(api.writes) == 2


def test_new_push_during_status_lookup_prevents_writing_an_outdated_comment(tmp_path, monkeypatch):
    api = FakeGitHub()
    galleries = site.prepare_site(api, tmp_path / "site", BASE_URL)
    site.update_comments(api, galleries, publication_run_id=201)
    original_items = api.items

    def push_during_lookup(path, key=None):
        result = original_items(path, key)
        if key == "workflow_runs":
            api.pulls[0]["head"]["sha"] = SECOND_SHA
        return result

    monkeypatch.setattr(api, "items", push_during_lookup)
    site.update_status(api, "failed", 202, ci_run_id=101, ci_attempt=1)

    assert len(api.writes) == 1


@pytest.mark.parametrize("option", ["--ci-run-id", "--ci-attempt"])
def test_status_cli_requires_run_id_and_attempt_together(monkeypatch, option):
    monkeypatch.setattr(
        "sys.argv",
        [
            "gallery",
            "status",
            "--publication",
            "preparing",
            "--publication-run-id",
            "201",
            option,
            "1",
        ],
    )

    with pytest.raises(SystemExit) as raised:
        site.main()

    assert raised.value.code == 2


class FakeGitHub:
    def __init__(self):
        self.pulls = [_pull(1)]
        self.runs = {101: _run(1, 101)}
        self.artifacts = [_artifact(101)]
        self.archives = {
            101: _archive(
                {
                    "1440x900/speech.png": _png(),
                    "1440x900/index.html": '<script src="https://attacker.example"></script>',
                }
            )
        }
        self.commits = {}
        self.comments = {1: [], 2: []}
        self.downloads = []
        self.writes = []

    def get(self, path):
        if path == "":
            return {"id": 10}
        if path == "actions/workflows/ci.yml":
            return {"id": 9}
        if path.startswith("actions/runs/"):
            return self.runs[int(path.rsplit("/", 1)[1])]
        if path.startswith("pulls/"):
            return deepcopy(
                next(pull for pull in self.pulls if pull["number"] == int(path.split("/")[1]))
            )
        raise AssertionError(path)

    def items(self, path, key=None):
        if path.startswith("pulls?"):
            return deepcopy([pull for pull in self.pulls if pull["state"] == "open"])
        if key == "workflow_runs":
            sha = parse_qs(urlsplit(path).query)["head_sha"][0]
            return [run for run in self.runs.values() if run["head_sha"] == sha]
        if key == "artifacts":
            return self.artifacts
        if path.startswith("pulls/"):
            return self.commits[int(path.split("/")[1])]
        if path.startswith("issues/"):
            return self.comments[int(path.split("/")[1])]
        raise AssertionError(path)

    def download(self, artifact_id):
        self.downloads.append(artifact_id)
        return self.archives[artifact_id]

    def write(self, method, path, body):
        self.writes.append((method, path, body))
        if method == "PATCH":
            for comments in self.comments.values():
                for comment in comments:
                    if comment["id"] == int(path.rsplit("/", 1)[1]):
                        comment["body"] = body["body"]
        else:
            self.comments[int(path.split("/")[1])].append(
                {"id": 99, "user": {"login": "github-actions[bot]"}, "body": body["body"]}
            )


def _pull(number, sha=FIRST_SHA):
    return {
        "number": number,
        "title": f"UI change {number}",
        "state": "open",
        "head": {"repo": {"id": 11}, "ref": f"feat/{number}-ui", "sha": sha},
        "base": {"ref": "development"},
    }


def _run(number, run_id, sha=FIRST_SHA):
    return {
        "id": run_id,
        "workflow_id": 9,
        "event": "pull_request",
        "status": "completed",
        "conclusion": "success",
        "head_repository": {"id": 11},
        "head_branch": f"feat/{number}-ui",
        "head_sha": sha,
        "run_attempt": 1,
        "run_started_at": "2026-10-09T07:00:00Z",
        "pull_requests": [{"number": number, "base": {"ref": "development"}}],
    }


def _artifact(run_id, sha=FIRST_SHA, number=1):
    return {
        "id": run_id,
        "name": "ui-gallery",
        "expired": False,
        "size_in_bytes": 1024,
        "created_at": "2026-10-09T07:05:00Z",
        "workflow_run": {
            "id": run_id,
            "repository_id": 10,
            "head_repository_id": 11,
            "head_branch": f"feat/{number}-ui",
            "head_sha": sha,
        },
    }


def _archive(files):
    output = io.BytesIO()
    with ZipFile(output, "w") as zipped:
        for path, content in files.items() if isinstance(files, dict) else files:
            entry = ZipInfo(path)
            # Keep malformed paths in the fixture even when Windows rewrites them.
            entry.filename = path
            zipped.writestr(entry, content)
    return output.getvalue()


def _png(metadata=False, gamma=False):
    def chunk(kind, content):
        return (
            struct.pack(">I", len(content))
            + kind
            + content
            + struct.pack(">I", zlib.crc32(kind + content))
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    color = chunk(b"gAMA", struct.pack(">I", 45455)) if gamma else b""
    text = chunk(b"tEXt", b"Comment\x00private metadata") if metadata else b""
    return (
        site.PNG_SIGNATURE
        + chunk(b"IHDR", header)
        + color
        + text
        + chunk(b"IDAT", zlib.compress(b"\x00\x11\x22\x33"))
        + chunk(b"IEND", b"")
    )
