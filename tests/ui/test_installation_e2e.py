from __future__ import annotations

from itertools import pairwise


def test_installation_summary_offers_download_and_calibration_only_on_request(
    qtbot, tmp_path, monkeypatch
):
    from pogled_assist.installation_check import TOBII_DOWNLOAD_URL, InstallationItem
    from pogled_assist.ui import installation_window

    opened = []
    monkeypatch.setattr(
        installation_window.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toString()) or True,
    )
    window = installation_window.InstallationWindow(tmp_path, auto_check=False)
    qtbot.addWidget(window)
    window._show_results([InstallationItem("software", "Tobii softver", "Pronađen", "")])
    window._finished()
    assert window.calibrate_button.isEnabled()
    assert opened == []
    window.download_button.click()
    assert opened == [TOBII_DOWNLOAD_URL]
    actions = []
    monkeypatch.setattr(window, "_start", lambda action, result: actions.append(action))
    window.calibrate_button.click()
    assert actions == [installation_window.launch_tobii_guest_calibration]
    window._show_results(
        [InstallationItem("software", "Tobii softver", "Potrebna instalacija", "")]
    )
    window._finished()
    assert not window.calibrate_button.isEnabled()


def test_installation_summary_keeps_rows_at_the_top_with_bold_titles(qtbot, tmp_path):
    from PySide6.QtWidgets import QLabel

    from pogled_assist.installation_check import InstallationItem
    from pogled_assist.ui import installation_window

    window = installation_window.InstallationWindow(tmp_path, auto_check=False)
    qtbot.addWidget(window)
    window.resize(900, 650)
    window.show()
    window._show_results(
        [
            InstallationItem("speech", "Govor", "Spremno", "Standardni glas radi bez interneta."),
            InstallationItem("software", "Tobii softver", "Pronađen", ""),
            InstallationItem("device", "Tobii uređaj", "Nije prepoznat", "Povežite uređaj."),
        ]
    )
    qtbot.waitUntil(lambda: len(window.result_rows()) == 3 and window.result_rows()[2].y() > 0)

    margins = window.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (24, 24, 24, 24)
    rows = window.result_rows()
    labels = [row.findChildren(QLabel) for row in rows]
    assert [[label.text() for label in row] for row in labels] == [
        ["Govor — Spremno", "Standardni glas radi bez interneta."],
        ["Tobii softver — Pronađen"],
        ["Tobii uređaj — Nije prepoznat", "Povežite uređaj."],
    ]
    for row in labels:
        assert row[0].font().bold()
        assert all(not label.font().bold() for label in row[1:])
    # Rows start at the top of the list and keep a fixed 12 px gap, whatever the height.
    assert rows[0].y() == 0
    for previous, row in pairwise(rows):
        assert row.y() - (previous.y() + previous.height()) == 12
    assert window.results_scroll.viewport().height() > rows[-1].geometry().bottom() + 100
