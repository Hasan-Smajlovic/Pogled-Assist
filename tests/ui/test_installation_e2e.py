from __future__ import annotations


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
