"""Streaming support archives and their readable technical summary."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .recording_metadata import json_bytes
from .tracking.gaze_check_report import GazeCheckReport, report_text


def export_files(
    item: dict, trace: tuple[Path, ...], report: GazeCheckReport | None
) -> tuple[dict[str, bytes | Path], dict | None]:
    files = {
        **{path.name: path for path in trace},
        "kontekst.json": json_bytes(item["context"]),
        "sazetak.txt": recording_text(item).encode("utf-8"),
    }
    selected = None
    if report is not None:
        report.validate()
        files.update(
            {
                "provjera/rezultat.json": report.to_json(),
                "provjera/izvjestaj.txt": report_text(report).encode("utf-8"),
            }
        )
        selected = {
            "id": report.id,
            "started_at": report.started_at,
            "state": report.state,
            "simulated": report.simulated,
            "eye_tracking_policy": report.settings.get("eye_tracking_policy"),
        }
    return files, selected


def export_manifest(item: dict, files: dict[str, bytes | Path], selected: dict | None) -> dict:
    return {
        "schema_version": 1,
        "recording": {key: value for key, value in item.items() if key != "analysis"},
        "selected_gaze_check": selected,
        "files": [{"path": name, **_payload_info(data)} for name, data in files.items()],
    }


def write_export(destination: Path, files: dict[str, bytes | Path]) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=".support-export-", delete=False
        ) as stream:
            temporary = Path(stream.name)
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            for name, payload in files.items():
                if isinstance(payload, Path):
                    digest = hashlib.sha256()
                    with (
                        payload.open("rb") as source,
                        archive.open(name, "w", force_zip64=True) as target,
                    ):
                        for chunk in iter(lambda: source.read(256 * 1024), b""):
                            target.write(chunk)
                            digest.update(chunk)
                    expected = json.loads(files["manifest.json"])["files"]
                    if digest.hexdigest() != next(
                        item["sha256"] for item in expected if item["path"] == name
                    ):
                        raise ValueError("Recording changed during export")
                else:
                    archive.writestr(name, payload)
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        # Keep the exact path for which Windows asked about overwriting.
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _payload_info(payload: bytes | Path) -> dict:
    if isinstance(payload, bytes):
        return dict(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    digest = hashlib.sha256()
    size = 0
    with payload.open("rb") as source:
        for chunk in iter(lambda: source.read(256 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return dict(bytes=size, sha256=digest.hexdigest())


def recording_text(item: dict) -> str:
    labels = {
        "manual": "Ručno zaustavljeno",
        "time": "Isteklo trajanje",
        "size": "Limit 32 MiB",
        "shutdown": "Zatvorena aplikacija",
        "writer_error": "Greška zapisivanja",
        "missing_end": "Nedostaje potvrđeni završetak",
        "missing_segments": "Nedostaju segmenti snimka",
    }
    analysis = item.get("analysis", {})
    lines = [
        "POGLED ASSIST · DIJAGNOSTIČKO SNIMANJE",
        f"ID: {item['id']}",
        f"Početak: {item.get('started_at')}",
        f"Kraj: {item.get('ended_at')}",
        "Trajanje: "
        + (
            "Nije dostupno"
            if item.get("duration_seconds") is None
            else f"{item['duration_seconds']:.3f} s"
        ),
        f"Razlog: {labels.get(item.get('reason'), item.get('reason'))}",
        f"Potpun snimak: {'Da' if item.get('complete') else 'Ne'}",
        f"Završni zapis: {'Da' if item.get('session_end_present') else 'Ne'}",
        "Nedostajući segmenti: " + json.dumps(item.get("segment_gaps", [])),
        "Lista nedostajućih segmenata skraćena: " + str(item.get("segment_gaps_truncated", False)),
        "Zdravlje samo ovog snimka: " + json.dumps(item.get("health", {}), ensure_ascii=False),
        "",
        "POČETNE POSTAVKE I OKRUŽENJE",
        json.dumps(item.get("context", {}), ensure_ascii=False, indent=2),
        "",
        "ZABILJEŽENI DOGAĐAJI",
        json.dumps(analysis.get("events", {}), ensure_ascii=False),
        "Razlozi završetka odabira: "
        + json.dumps(analysis.get("selection_end_reasons_from_events", {}), ensure_ascii=False),
        "",
        *_analysis_text(analysis.get("analysis", {})),
        "Koordinate i geometrija kontrola mogu otkriti aktivnost. Nema poruka, zvuka, ekrana, biblioteke ni ključeva.",
        "Važenje SDK podataka nije dokaz fizički zatvorenog oka. Završeni odabir nije dokaz namjeravane mete.",
        "Nedostajući i izostavljeni događaji ograničavaju zaključke; ovim se ne mjeri Tobii preciznost bez poznate mete.",
    ]
    return "\n".join(lines) + "\n"


def _analysis_text(analysis):
    labels = {
        "outcomes_by_surface": "Ishodi po površini",
        "settings_intervals": "Intervali postavki",
        "outcomes_by_settings_interval": "Ishodi po postavkama",
        "hold_outcomes": "Ishodi zadržavanja",
        "hold_duration": "Trajanje zadržavanja (ms)",
        "hold_coverage": "Obuhvat zadržavanja",
        "partial_hold_outcomes": "Djelimično zabilježena zadržavanja",
        "partial_hold_duration": "Puno trajanje djelimičnih zadržavanja (ms)",
        "discarded_credit_ms": "Odbačeni napredak (ms)",
        "latency": "Kašnjenja (ms)",
        "missing_counter_intervals": "Nedostajući intervali brojača",
        "reason_totals_from_counters": "Razlozi iz zbirnih brojača",
        "partial_selection_attempts": "Djelimični pokušaji odabira",
        "evidence_incomplete": "Dokazi nepotpuni",
        "details_truncated": "Detalji skraćeni",
    }
    return [
        f"{label}: {json.dumps(analysis.get(key), ensure_ascii=False)}"
        for key, label in labels.items()
    ]
