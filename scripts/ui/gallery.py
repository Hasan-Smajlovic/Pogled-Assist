"""Shared screenshot selection and HTML for local and trusted CI galleries."""

from html import escape

# Order the representative states by the reviewer's task, not by filename.
GROUPS = {
    "speech": (
        "Speech",
        (
            "speech",
            "speech-categories",
            "speech-answers",
            "phrases",
            "speech-editor",
            "speech-alarm",
            "speech-sleep",
            "speech-exit",
            "speech-arabic",
            "speech-arabic-letters",
            "speech-arabic-symbols",
            "speech-arabic-marks",
            "speech-arabic-editor",
        ),
    ),
    "keyboards": (
        "Keyboard and Controller",
        (
            "keyboard-letters",
            "keyboard-numpad",
            "keyboard-symbols",
            "keyboard-latin-paged",
            "keyboard-arabic",
            "keyboard-arabic-symbols",
            "controller-general",
            "controller-keyboard",
            "controller-settings",
            "controller-latin-paged",
            "controller-arabic",
            "controller-arabic-symbols",
        ),
    ),
    "settings": (
        "Settings",
        (
            "settings-general",
            "settings-gaze",
            "settings-gaze-hold",
            "settings-gaze-one-eye",
            "settings-gaze-pointer",
            "settings-gaze-stability",
            "settings-gaze-stability-off",
            "settings-speech",
            "settings-learned-words",
            "settings-version-warning",
        ),
    ),
    "tracking": (
        "Tracking and selection",
        (
            "hotbar",
            "hotbar-paused",
            "hotbar-retrying",
            "hotbar-simulation",
            "hotbar-one-eye-ready",
            "hotbar-selection-held",
            "selection-progress",
            "selection-held",
        ),
    ),
    "gaze-check": (
        "Gaze check",
        (
            "gaze-check-position",
            "gaze-check-precision",
            "gaze-check-results-details",
            "gaze-check-report-trials",
            "gaze-check-report-context",
            "gaze-check-result-interrupted",
            "gaze-check-history",
            "gaze-check-save-error",
            "gaze-check-trial",
            "gaze-check-trial-keyboard",
            "gaze-check-trial-words",
            "gaze-check-trial-held",
            "gaze-check-trial-wrong",
            "gaze-check-free",
        ),
    ),
    "voice": (
        "Voice and account",
        (
            "speech-preparing",
            "speech-voice-standard",
            "speech-voice-cached",
            "speech-voice-partial",
            "settings-elevenlabs-connected",
            "settings-elevenlabs-replacing",
            "settings-elevenlabs-permission",
            "settings-elevenlabs-critical-credits",
            "settings-saved-audio",
        ),
    ),
}

OVERVIEW = (
    "speech",
    "settings-general",
    "hotbar",
    "speech-arabic",
    "keyboard-letters",
    "controller-general",
)
CORE_NAMES = frozenset(name for _, names in GROUPS.values() for name in names)


def group_for(name: str) -> str:
    if name.startswith(("keyboard-", "controller-")):
        return "keyboards"
    if name.startswith(("hotbar", "selection-", "speech-tracking-")):
        return "tracking"
    if name.startswith("gaze-check-"):
        return "gaze-check"
    if name.startswith(("settings-elevenlabs-", "speech-voice-")) or name in (
        "settings-efendija",
        "settings-saved-audio",
        "speech-preparing",
        "speech-speaking",
        "settings-speech-preparing",
        "settings-speech-speaking",
    ):
        return "voice"
    if name.startswith("settings-"):
        return "settings"
    if name == "phrases" or name == "speech" or name.startswith("speech-"):
        return "speech"
    return "other"


def select_names(profile: str, groups: tuple[str, ...] = ()) -> frozenset[str] | None:
    """None selects every state; an empty set selects none."""
    if profile not in ("core", "full") or set(groups) - GROUPS.keys():
        raise ValueError("Unknown UI gallery profile or group")
    if profile == "full":
        return None
    return frozenset(name for name in CORE_NAMES if not groups or group_for(name) in groups)


def gallery_content(images: dict[str, str]) -> str:
    """Render only supplied filenames/titles; never consume artifact HTML or metadata."""

    def card(name: str) -> str:
        title = escape(images[name])
        filename = escape(f"{name}.png", quote=True)
        return (
            f'<article><h3>{title}</h3><a href="{filename}" target="_blank" rel="noopener">'
            f'<img loading="lazy" src="{filename}" alt="{title}"></a></article>'
        )

    sections = []
    navigation = []
    overview = [name for name in OVERVIEW if name in images]
    if overview:
        navigation.append('<a href="#overview">Overview</a>')
        sections.append(
            '<section id="overview"><h2>Overview</h2><div class="shots">'
            + "".join(card(name) for name in overview)
            + "</div></section>"
        )
    for key, (label, core) in (*GROUPS.items(), ("other", ("Other previews", ()))):
        selected = {name for name in images if group_for(name) == key}
        ordered = [name for name in core if name in selected] + sorted(selected - set(core))
        if not ordered:
            continue
        navigation.append(f'<a href="#{key}">{label} ({len(ordered)})</a>')
        sections.append(
            f'<section id="{key}"><h2>{label} <small>{len(ordered)}</small></h2>'
            '<div class="shots">' + "".join(card(name) for name in ordered) + "</div></section>"
        )
    return (
        f"<p>{len(images)} screenshots. Click a thumbnail to open the full-size image in a new tab. "
        'Overview reuses the main images.</p><nav aria-label="Screenshot groups">'
        + " · ".join(navigation)
        + "</nav>"
        + "".join(sections)
    )


def page_html(title: str, content: str) -> str:
    return f"""<!doctype html>
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
    section {{ scroll-margin-top: 16px; }}
    .shots {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr));
      gap: 16px; }}
    article {{ overflow: hidden; border: 1px solid #303746; border-radius: 12px;
      background: #151923; padding: 16px; min-width: 0; }}
    h2 {{ font-size: 20px; }}
    h3 {{ margin: 0 0 12px; font-size: 16px; overflow-wrap: anywhere; }}
    small, p {{ color: #aeb8c8; overflow-wrap: anywhere; }}
    a {{ color: #9ac7ff; }}
    nav {{ line-height: 2; }}
    .shots a {{ display: flex; align-items: center; height: 200px; background: #08090c; }}
    img {{ display: block; max-width: 100%; max-height: 100%; width: auto; height: auto;
      margin: auto; object-fit: contain; }}
    a:focus-visible {{ outline: 3px solid #9ac7ff; outline-offset: 3px; }}
  </style>
</head>
<body>
  <header><h1>{escape(title)}</h1>
    <p>Generated from Qt widgets with synthetic data. Hardware and Windows input are disabled.</p>
  </header>
  <main>{content}</main>
</body>
</html>
"""
