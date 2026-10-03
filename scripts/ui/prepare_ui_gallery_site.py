"""Build a public review site from CI images without publishing PR-supplied HTML."""

from __future__ import annotations

import argparse
import io
import json
import re
import stat
import struct
import subprocess
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from html import escape
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

REPOSITORY = "Hasan-Smajlovic/Pogled-Assist"
COMMENT_MARKER = "<!-- pogled-assist-ui-gallery -->"
RESOLUTIONS = ("1280x720", "1440x900")
PREVIEWS = (
    ("speech.png", "Speech"),
    ("settings-general.png", "Settings"),
    ("hotbar.png", "Hotbar"),
    ("speech-arabic.png", "Arabic Speech"),
    ("keyboard-letters.png", "Keyboard"),
    ("controller-general.png", "Controller"),
)
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_GALLERY_BYTES = 128 * 1024 * 1024
MAX_SITE_BYTES = 512 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Preserve color and pixel data without publishing embedded text.
PNG_RENDERING_CHUNKS = frozenset(
    (b"IHDR", b"PLTE", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"IDAT", b"IEND")
)


def prepare_site(api, output_dir: Path, base_url: str) -> list[dict]:
    """Rebuild all open PR galleries so one deployment cannot erase another PR."""
    base_url = _pages_url(base_url)
    source = GallerySource(api)
    comments = []
    cards = []
    site_bytes = 0
    _prepare_directory(output_dir)
    for pull in source.pulls:
        gallery = source.find(pull)
        comments.append(_comment_payload(pull, gallery, base_url))
        if gallery is None:
            continue
        site_bytes += gallery.size
        if site_bytes > MAX_SITE_BYTES:
            raise ValueError("The UI gallery site exceeds its 512 MiB size limit.")
        _write_gallery(output_dir / gallery.path, gallery)
        cards.append(gallery.card())
    content = "\n".join(cards) or "<p>No open pull requests have an available UI gallery.</p>"
    _write_page(output_dir / "index.html", "Pogled Assist UI galleries", content)
    return comments


def update_comments(api, galleries: list[dict]) -> None:
    """Update only our bot's gallery comment, while the PR head still matches."""
    for gallery in galleries:
        number = gallery["number"]
        pull = api.get(f"pulls/{number}")
        if pull["state"] != "open" or pull["head"]["sha"] != gallery["head_sha"]:
            continue
        comments = api.items(f"issues/{number}/comments?per_page=100")
        existing = next((comment for comment in comments if _is_gallery_comment(comment)), None)
        _update_comment(api, gallery, existing)


def read_images(archive: bytes) -> dict[str, bytes]:
    """Read bounded PNG files; never extract or reuse HTML from a PR artifact."""
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise ValueError("The UI archive is too large.")
    images = {}
    with ZipFile(io.BytesIO(archive)) as zipped:
        entries = zipped.infolist()
        _check_archive_size(entries)
        for entry in entries:
            path = _image_path(entry, images)
            if path is None:
                continue
            images[path] = _safe_png(zipped.read(entry))
    if not images:
        raise ValueError("The UI archive contains no images.")
    return images


@dataclass(frozen=True)
class Gallery:
    pull: dict
    run: dict
    artifact: dict
    images: dict[str, bytes]

    @property
    def path(self) -> str:
        return f"pr-{self.pull['number']}/artifact-{self.artifact['id']}"

    @property
    def size(self) -> int:
        return sum(len(content) for content in self.images.values())

    def card(self) -> str:
        return (
            f'<article><h2><a href="{self.path}/">PR #{self.pull["number"]}: '
            f'{escape(self.pull["title"])}</a></h2>'
            f'<p>Commit <code>{self.run["head_sha"][:7]}</code> · '
            f'{len(self.images)} images · CI: {escape(self.run["conclusion"] or "unknown")}</p>'
            "</article>"
        )


class GallerySource:
    """Select retained CI artifacts that still belong to each open PR."""

    def __init__(self, api):
        self.api = api
        self.repository_id = api.get("")["id"]
        self.workflow_id = api.get("actions/workflows/ci.yml")["id"]
        self.pulls = [
            pull
            for pull in api.items("pulls?state=open&per_page=100")
            if pull["base"]["ref"] in ("development", "master") and pull["head"]["repo"]
        ]
        self.artifacts = api.items("actions/artifacts?name=ui-gallery&per_page=100", "artifacts")
        self.runs: dict[int, dict] = {}
        self.commits: dict[int, set[str]] = {}

    def find(self, pull: dict) -> Gallery | None:
        candidates = sorted(
            self.artifacts,
            key=lambda artifact: (
                (artifact.get("workflow_run") or {}).get("head_sha") == pull["head"]["sha"],
                artifact["id"],
            ),
            reverse=True,
        )
        for artifact in candidates:
            run = self._matching_run(artifact, pull)
            if run is None:
                continue
            if not self._has_commit(pull, run["head_sha"]):
                continue
            images = self._read_images(artifact)
            if images is not None:
                return Gallery(pull, run, artifact, images)
        return None

    def _matching_run(self, artifact: dict, pull: dict) -> dict | None:
        if not _matches_artifact(artifact, pull, self.repository_id):
            return None
        source = artifact["workflow_run"]
        run_id = source["id"]
        if run_id not in self.runs:
            self.runs[run_id] = self.api.get(f"actions/runs/{run_id}")
        run = self.runs[run_id]
        if not _matches_pull(run, pull, self.workflow_id, source["head_sha"]):
            return None
        return run

    def _has_commit(self, pull: dict, sha: str) -> bool:
        if sha == pull["head"]["sha"]:
            return True
        number = pull["number"]
        if number not in self.commits:
            self.commits[number] = {
                commit["sha"] for commit in self.api.items(f"pulls/{number}/commits")
            }
        return sha in self.commits[number]

    def _read_images(self, artifact: dict) -> dict[str, bytes] | None:
        try:
            return read_images(self.api.download(artifact["id"]))
        except (BadZipFile, ValueError, OSError, RuntimeError, zlib.error) as error:
            print(f"Skipped UI artifact {artifact['id']}: {error}")
            return None


def _pages_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    _check_pages_origin(parsed)
    if parsed.query or parsed.fragment:
        raise ValueError("The Pages base URL must be an HTTPS site URL.")
    return base_url.rstrip("/")


def _check_pages_origin(parsed) -> None:
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("The Pages base URL must be an HTTPS site URL.")
    if parsed.username or parsed.password:
        raise ValueError("The Pages base URL must be an HTTPS site URL.")


def _prepare_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError("The site output directory must be empty.")


def _matches_artifact(artifact: dict, pull: dict, repository_id: int) -> bool:
    if artifact["name"] != "ui-gallery" or artifact["expired"]:
        return False
    if artifact["size_in_bytes"] > MAX_ARCHIVE_BYTES:
        return False
    source = artifact.get("workflow_run") or {}
    if source.get("repository_id") != repository_id:
        return False
    return (
        source.get("head_repository_id") == pull["head"]["repo"]["id"]
        and source.get("head_branch") == pull["head"]["ref"]
    )


def _matches_pull(run: dict, pull: dict, workflow_id: int, head_sha: str) -> bool:
    if not _is_completed_ci_run(run, workflow_id):
        return False
    if not _matches_head(run, pull, head_sha):
        return False
    return _matches_association(run.get("pull_requests") or [], pull)


def _is_completed_ci_run(run: dict, workflow_id: int) -> bool:
    if run["workflow_id"] != workflow_id:
        return False
    return run["event"] == "pull_request" and run["status"] == "completed"


def _matches_head(run: dict, pull: dict, head_sha: str) -> bool:
    if (run.get("head_repository") or {}).get("id") != pull["head"]["repo"]["id"]:
        return False
    if run["head_branch"] != pull["head"]["ref"]:
        return False
    return run["head_sha"] == head_sha and re.fullmatch(r"[0-9a-f]{40}", head_sha) is not None


def _matches_association(associations: list[dict], pull: dict) -> bool:
    # Fork runs can omit PR associations; their repository, branch and commit still must match.
    if not associations:
        return True
    return any(
        item["number"] == pull["number"] and item["base"]["ref"] == pull["base"]["ref"]
        for item in associations
    )


def _comment_payload(pull: dict, gallery: Gallery | None, base_url: str) -> dict:
    body = (
        f"{COMMENT_MARKER}\nNo UI gallery is available for this PR. "
        "Its CI artifact may have expired, or rendering has not completed. "
        "Run CI again to generate new previews."
    )
    if gallery is not None:
        body = _comment(base_url, gallery)
    return {
        "number": pull["number"],
        "head_sha": pull["head"]["sha"],
        "body": body,
        "create": gallery is not None,
    }


def _is_gallery_comment(comment: dict) -> bool:
    user = comment.get("user") or {}
    body = comment["body"] or ""
    return user.get("login") == "github-actions[bot]" and body.startswith(COMMENT_MARKER)


def _update_comment(api, gallery: dict, existing: dict | None) -> None:
    if existing is None:
        if gallery["create"]:
            api.write("POST", f"issues/{gallery['number']}/comments", {"body": gallery["body"]})
        return
    if existing["body"] != gallery["body"]:
        api.write("PATCH", f"issues/comments/{existing['id']}", {"body": gallery["body"]})


def _check_archive_size(entries: list) -> None:
    if len(entries) > 256 or sum(entry.file_size for entry in entries) > MAX_GALLERY_BYTES:
        raise ValueError("The expanded UI archive is too large.")


def _archive_path(entry) -> PurePosixPath:
    path = PurePosixPath(entry.filename)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("The UI archive contains an unsafe path or file type.")
    mode = stat.S_IFMT(entry.external_attr >> 16)
    if "\\" in entry.filename or mode not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise ValueError("The UI archive contains an unsafe path or file type.")
    return path


def _image_path(entry, images: dict[str, bytes]) -> str | None:
    path = _archive_path(entry)
    if entry.is_dir() or path.suffix != ".png":
        return None
    _check_image_name(path)
    if entry.file_size > MAX_IMAGE_BYTES or path.as_posix() in images:
        raise ValueError("The UI archive contains an unexpected image.")
    return path.as_posix()


def _check_image_name(path: PurePosixPath) -> None:
    if len(path.parts) != 2:
        raise ValueError("The UI archive contains an unexpected image.")
    if path.parts[0] not in RESOLUTIONS:
        raise ValueError("The UI archive contains an unexpected image.")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.png", path.name):
        raise ValueError("The UI archive contains an unexpected image.")


@dataclass(frozen=True)
class PngChunk:
    raw: bytes
    end: int

    @property
    def kind(self) -> bytes:
        return self.raw[4:8]

    @property
    def data(self) -> bytes:
        return self.raw[8:-4]


def _safe_png(content: bytes) -> bytes:
    if not content.startswith(PNG_SIGNATURE) or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("An image is not a bounded PNG file.")
    chunks = _png_chunks(content)
    header = _read_png_header(chunks)
    output = bytearray(PNG_SIGNATURE + header.raw)
    has_data = False
    for chunk in chunks:
        output.extend(_rendering_chunk(chunk))
        has_data = has_data or chunk.kind == b"IDAT"
        if chunk.kind == b"IEND":
            _check_png_end(chunk, len(content), has_data)
            return bytes(output)
    raise ValueError("A PNG image is incomplete or has trailing content.")


def _rendering_chunk(chunk: PngChunk) -> bytes:
    if chunk.kind == b"IHDR":
        raise ValueError("A PNG image has a duplicate header.")
    return chunk.raw if chunk.kind in PNG_RENDERING_CHUNKS else b""


def _png_chunks(content: bytes) -> Iterator[PngChunk]:
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(content):
        length = struct.unpack_from(">I", content, offset)[0]
        end = offset + length + 12
        if end > len(content):
            return
        yield _read_png_chunk(content[offset:end], end)
        offset = end


def _read_png_chunk(raw: bytes, end: int) -> PngChunk:
    chunk = PngChunk(raw, end)
    checksum = struct.unpack_from(">I", raw, len(raw) - 4)[0]
    if zlib.crc32(chunk.kind + chunk.data) != checksum:
        raise ValueError("A PNG chunk has an invalid checksum.")
    return chunk


def _read_png_header(chunks: Iterator[PngChunk]) -> PngChunk:
    header = next(chunks, None)
    if header is None:
        raise ValueError("A PNG image is incomplete or has trailing content.")
    if header.kind != b"IHDR" or len(header.data) != 13:
        raise ValueError("A PNG image has no valid header.")
    width, height = struct.unpack_from(">II", header.data)
    _check_png_dimensions(width, height)
    return header


def _check_png_dimensions(width: int, height: int) -> None:
    if not (0 < width <= 4096 and 0 < height <= 4096):
        raise ValueError("A PNG image has unexpected dimensions.")


def _check_png_end(chunk: PngChunk, content_size: int, has_data: bool) -> None:
    if chunk.data or chunk.end != content_size:
        raise ValueError("A PNG image is incomplete or has trailing content.")
    if not has_data:
        raise ValueError("A PNG image is incomplete or has trailing content.")


def _write_gallery(directory: Path, gallery: Gallery) -> None:
    pull, run, images = gallery.pull, gallery.run, gallery.images
    links = []
    for resolution in RESOLUTIONS:
        selected = [path for path in sorted(images) if path.startswith(f"{resolution}/")]
        if not selected:
            continue
        target = directory / resolution
        target.mkdir(parents=True, exist_ok=True)
        cards = []
        for path in selected:
            name = PurePosixPath(path).name
            (target / name).write_bytes(images[path])
            title = name.removesuffix(".png").replace("-", " ").capitalize()
            cards.append(
                f'<article><h2>{title}</h2><a href="{name}">'
                f'<img loading="lazy" src="{name}" alt="{title}"></a></article>'
            )
        _write_page(
            target / "index.html",
            f"PR #{pull['number']} · {resolution}",
            '<p><a href="../">Back to resolutions</a></p>' + "\n".join(cards),
        )
        links.append(f'<li><a href="{resolution}/">{resolution}: {len(selected)} images</a></li>')
    _write_page(
        directory / "index.html",
        f"PR #{pull['number']}: {pull['title']}",
        f'<p>Rendered commit <code>{run["head_sha"]}</code>.</p>'
        '<p><a href="../../">All PR galleries</a></p><ul>' + "".join(links) + "</ul>",
    )


def _write_page(path: Path, title: str, content: str) -> None:
    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self';
    style-src 'unsafe-inline'; base-uri 'none'">
  <title>{escape(title)}</title>
  <style>
    body {{ margin: 0; padding: 24px; background: #0c0e12; color: #f6f7fb;
      font-family: "Segoe UI", Arial, sans-serif; }}
    header, main {{ max-width: 1440px; margin: auto; }}
    main {{ display: grid; gap: 24px; }}
    article {{ overflow: hidden; border: 1px solid #303746; border-radius: 12px;
      background: #151923; padding: 16px; }}
    h2 {{ font-size: 18px; }}
    p {{ color: #aeb8c8; overflow-wrap: anywhere; }}
    a {{ color: #9ac7ff; }}
    img {{ display: block; max-width: 100%; height: auto; margin: auto; }}
  </style>
</head>
<body>
  <header><h1>{escape(title)}</h1>
    <p>Generated from Qt widgets with synthetic data. Hardware and Windows input are disabled.</p>
  </header>
  <main>{content}</main>
</body>
</html>
""",
        encoding="utf-8",
    )


def _comment(base_url: str, gallery: Gallery) -> str:
    pull, run, artifact = gallery.pull, gallery.run, gallery.artifact
    url = f"{base_url}/{gallery.path}"
    run_url = f"https://github.com/{REPOSITORY}/actions/runs/{run['id']}"
    lines = [
        COMMENT_MARKER,
        "### UI previews",
        "",
        f"Rendered commit: `{run['head_sha'][:7]}` · CI: **{run['conclusion'] or 'unknown'}**",
        "",
        f"[Open the full gallery]({url}/) · "
        f"[Download all images]({run_url}/artifacts/{artifact['id']}) · [CI run]({run_url})",
        "",
        "Generated with synthetic data, without Tobii hardware or real Windows input.",
    ]
    if run["head_sha"] != pull["head"]["sha"]:
        lines.extend(["", "These previews are from an earlier commit in this PR."])
    lines.extend(["", "Resolutions: " + " · ".join(_resolution_links(url, gallery.images))])
    lines.extend(_preview_section(url, gallery.images))
    return "\n".join(lines)


def _resolution_links(url: str, images: dict[str, bytes]) -> list[str]:
    return [
        f"[{resolution}]({url}/{resolution}/)"
        for resolution in RESOLUTIONS
        if any(path.startswith(f"{resolution}/") for path in images)
    ]


def _preview_section(url: str, images: dict[str, bytes]) -> list[str]:
    previews = []
    for name, title in PREVIEWS:
        image = next(
            (f"{size}/{name}" for size in reversed(RESOLUTIONS) if f"{size}/{name}" in images),
            None,
        )
        if image:
            previews.append(f"**{title}**\n\n![{title}]({url}/{image})")
    if not previews:
        return []
    return [
        "",
        "<details>",
        "<summary>View main UI screenshots</summary>",
        "",
        "\n\n".join(previews),
        "",
        "</details>",
    ]


class GitHub:
    """Use the runner's GitHub CLI with each job's scoped token."""

    def get(self, path: str) -> dict:
        return json.loads(self._request(path))

    def items(self, path: str, key: str | None = None) -> list:
        pages = json.loads(self._request(path, "--paginate", "--slurp"))
        return [item for page in pages for item in (page[key] if key else page)]

    def download(self, artifact_id: int) -> bytes:
        return self._request(f"actions/artifacts/{artifact_id}/zip")

    def write(self, method: str, path: str, body: dict) -> None:
        self._request(path, "--method", method, "--input", "-", body=body)

    def _request(self, path: str, *options: str, body: dict | None = None) -> bytes:
        endpoint = f"repos/{REPOSITORY}" + (f"/{path}" if path else "")
        return subprocess.run(
            ["gh", "api", endpoint, *options],
            check=True,
            input=json.dumps(body).encode("utf-8") if body is not None else None,
            stdout=subprocess.PIPE,
            timeout=120,
        ).stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Prepare the Pages site with a read-only token.")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--comments", type=Path, required=True)
    build.add_argument("--base-url", required=True)
    comment = commands.add_parser("comment", help="Update gallery comments after deployment.")
    comment.add_argument("--comments", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "build":
        comments = prepare_site(GitHub(), arguments.output, arguments.base_url)
        arguments.comments.parent.mkdir(parents=True, exist_ok=True)
        arguments.comments.write_text(json.dumps(comments), encoding="utf-8")
    else:
        update_comments(GitHub(), json.loads(arguments.comments.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
