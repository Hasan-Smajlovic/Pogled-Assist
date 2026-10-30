"""Plain, content-free storage and persistence feedback for Diagnostics."""

from datetime import datetime

OUTPUTS = {"ordinary": "opći logovi", "manual": "ručni snimak"}
REASONS = {
    "write": "Greška zapisivanja",
    "text_write": "Greška tekstualnog zapisa",
    "json_write": "Greška strukturiranog zapisa",
    "text_open": "Tekstualni log nije otvoren",
    "json_open": "Strukturirani log nije otvoren",
    "text_rotation": "Rotacija tekstualnog loga nije uspjela",
    "text_flush": "Čuvanje tekstualnog loga nije potvrđeno",
    "json_flush": "Čuvanje strukturiranog loga nije potvrđeno",
    "metadata": "Greška završnog zapisa",
}


def storage_text(storage, persistence):
    state = {
        "ready": "Prostor je dostupan.",
        "protected_over_budget": "Zaštićeni podaci trenutno prelaze podešeni prostor.",
        "low_space": "Na disku nema dovoljno slobodnog prostora.",
        "cleanup_failed": "Brisanje starih logova nije uspjelo.",
        "unavailable": "Stanje prostora nije dostupno.",
    }.get(storage.get("state"), "Provjeravam prostor…")
    lines = [
        f"Svi logovi: {storage.get('usage_bytes', 0) / 1_000_000_000:.2f} / {storage.get('budget_bytes', 4_000_000_000) / 1_000_000_000:g} GB",
        f"Najstariji poznati zapis: {storage.get('oldest_at') or 'Nije poznato'}",
        state,
    ]
    failures = {
        OUTPUTS.get(item.get("output"), "nepoznat izlaz")
        for item in persistence.get("failures", [])
    }
    if failures:
        lines.append("Greška čuvanja: " + ", ".join(sorted(failures)) + ".")
    lines.extend(persistence_text(persistence))
    return "\n".join(lines)


def persistence_text(persistence):
    gaps = persistence.get("gaps", [])
    if not gaps:
        return ["Nema zabilježenih prekida čuvanja."]
    lines = [f"Zabilježeni prekidi čuvanja: {len(gaps)}."]
    for gap in reversed(gaps):
        output = OUTPUTS.get(gap.get("output"), "Nepoznat izlaz")
        reason = REASONS.get(gap.get("reason"), "Nepoznat razlog")
        recovered = "još traje" if gap.get("recovered_at") is None else _time(gap["recovered_at"])
        lines.append(
            f"{output} · {reason}\nPočetak: {_time(gap.get('started_at'))} · Oporavak: {recovered}"
        )
    if persistence.get("gaps_truncated"):
        lines.append("Prikaz je skraćen na posljednja 64 prekida.")
    return lines


def _time(value):
    try:
        return datetime.fromtimestamp(value).astimezone().strftime("%d.%m.%Y. %H:%M:%S %z")
    except (ValueError, TypeError, OverflowError, OSError):
        return "Nije poznato"
