from __future__ import annotations

from PySide6.QtCore import QPoint

from gaze_mouse.mouse_controller import (
    DOUBLE_LEFT_CLICK,
    LEFT_CLICK,
    RIGHT_CLICK,
    GazeMouseController,
    GazeScreenPoint,
    GazeSettings,
)


class FakeInput:
    def __init__(self):
        self.moves = []
        self.clicks = []

    def move_to(self, x, y):
        self.moves.append((x, y))

    def click(self, x, y, **options):
        self.clicks.append((x, y, options))


def make_controller():
    controller = GazeMouseController(
        toolbar_action_at=lambda _point: None,
        toolbar_action_center=lambda _action, _point: None,
        toolbar_contains=lambda _point: False,
    )
    controller._logical_screen_rect = (10, 20, 101, 201)
    controller._physical_screen_rect = (100, 200, 201, 401)
    controller._input = FakeInput()
    return controller


def test_screen_mapping_clamps_and_maps_logical_to_physical():
    controller = make_controller()

    low = controller._map_to_screen(-1.0, -1.0)
    middle = controller._map_to_screen(0.5, 0.5)
    high = controller._screen_point_from_logical(QPoint(999, 999))

    assert low.logical == QPoint(10, 20)
    assert low.physical == QPoint(100, 200)
    assert middle.logical == QPoint(60, 120)
    assert middle.physical == QPoint(200, 400)
    assert high.logical == QPoint(110, 220)
    assert high.physical == QPoint(300, 600)


def test_smoothing_uses_configured_weight_and_resets_with_settings():
    controller = make_controller()
    controller.update_settings(GazeSettings(smoothing=0.25))

    assert controller._smooth_physical(QPoint(0, 0)) == QPoint(0, 0)
    assert controller._smooth_physical(QPoint(100, 40)) == QPoint(25, 10)

    controller.update_settings(GazeSettings(smoothing=1.0))
    assert controller._smooth_physical(QPoint(100, 40)) == QPoint(100, 40)


def test_eye_gate_blocks_gaze_and_clears_active_interactions():
    controller = make_controller()
    positions = []
    controller.gaze_position_changed.connect(lambda point: positions.append(QPoint(point)))
    controller.set_mode(LEFT_CLICK)
    controller._target_anchor = QPoint(20, 20)

    controller.handle_gaze(0.5, 0.5, 1)
    controller.handle_eye_status(True, True)
    controller.handle_gaze(0.5, 0.5, 2)
    controller.handle_eye_status(True, False)

    assert positions == [QPoint(60, 120)]
    assert controller._input.moves == [(200, 400)]
    assert controller._target_anchor is None
    assert controller._both_eyes_open is False


def test_simulation_can_disable_pointer_movement_without_blocking_gaze():
    controller = GazeMouseController(
        toolbar_action_at=lambda _point: None,
        toolbar_action_center=lambda _action, _point: None,
        toolbar_contains=lambda _point: False,
        pointer_movement_enabled=False,
    )
    controller._logical_screen_rect = (10, 20, 101, 201)
    controller._physical_screen_rect = (100, 200, 201, 401)
    controller._input = FakeInput()
    positions = []
    controller.gaze_position_changed.connect(lambda point: positions.append(QPoint(point)))

    controller.handle_eye_status(True, True)
    controller.handle_gaze(0.5, 0.5, 1)

    assert positions == [QPoint(60, 120)]
    assert controller._input.moves == []


def test_click_modes_call_native_input_and_reset():
    controller = make_controller()
    fired = []
    controller.action_fired.connect(lambda action, point: fired.append((action, QPoint(point))))
    target = GazeScreenPoint(QPoint(20, 30), QPoint(200, 300))

    controller.set_mode(DOUBLE_LEFT_CLICK)
    controller._fire_click(DOUBLE_LEFT_CLICK, target)

    assert controller._input.clicks == [
        (200, 300, {"button": "left", "clicks": 2, "interval": 0.04})
    ]
    assert fired == [(DOUBLE_LEFT_CLICK, QPoint(200, 300))]
    assert controller.active_mode is None


def test_right_click_arms_direct_left_click_for_context_menu():
    controller = make_controller()
    target = GazeScreenPoint(QPoint(20, 30), QPoint(200, 300))
    controller.set_mode(RIGHT_CLICK)

    controller._fire_click(RIGHT_CLICK, target)

    assert controller._input.clicks == [(200, 300, {"button": "right"})]
    assert controller.active_mode == LEFT_CLICK
    assert controller._native_menu_click_pending is True


def test_target_dwell_opens_zoom_before_click():
    controller = make_controller()
    controller.update_settings(
        GazeSettings(dwell_ms=200, click_cooldown_ms=100, use_precision_zoom=True)
    )
    controller.set_mode(LEFT_CLICK)
    target = GazeScreenPoint(QPoint(30, 40), QPoint(130, 240))
    requested = []
    controller.click_zoom_requested.connect(lambda point: requested.append(QPoint(point)))

    controller._handle_target_dwell(target, 1000)
    controller._handle_target_dwell(target, 1499)
    controller._handle_target_dwell(target, 1500)
    controller._handle_target_dwell(target, 1699)
    controller._handle_target_dwell(target, 1700)

    assert requested == [QPoint(30, 40)]
    assert controller._pending_zoom_click_mode == LEFT_CLICK
    assert controller._input.clicks == []


def test_toolbar_dwell_waits_before_feedback_and_requires_leaving_to_repeat():
    controller = make_controller()
    controller.update_settings(
        GazeSettings(selection_pause_ms=250, dwell_ms=200, click_cooldown_ms=100)
    )
    actions = []
    progress = []
    controller.toolbar_action_requested.connect(actions.append)
    controller.interaction_progress_changed.connect(
        lambda _point, value, _label: progress.append(value)
    )

    controller._handle_toolbar_dwell("settings", QPoint(10, 10), 1000)
    controller._handle_toolbar_dwell("settings", QPoint(10, 10), 1249)

    assert actions == []
    assert progress == []

    controller._handle_toolbar_dwell("settings", QPoint(10, 10), 1250)
    controller._handle_toolbar_dwell("settings", QPoint(10, 10), 1449)
    controller._handle_toolbar_dwell("settings", QPoint(10, 10), 1450)
    controller._handle_toolbar_dwell("settings", QPoint(10, 10), 3000)

    assert actions == ["settings"]
    assert progress[0] == 0.0

    controller._reset_toolbar_dwell()
    controller._handle_toolbar_dwell("settings", QPoint(10, 10), 3100)
    controller._handle_toolbar_dwell("settings", QPoint(10, 10), 3350)
    controller._handle_toolbar_dwell("settings", QPoint(10, 10), 3550)

    assert actions == ["settings", "settings"]


def test_eye_loss_keeps_completed_toolbar_target_blocked_until_valid_gaze_leaves():
    controller = make_controller()
    controller.update_settings(
        GazeSettings(selection_pause_ms=250, dwell_ms=200, click_cooldown_ms=100)
    )
    actions = []
    controller.toolbar_action_requested.connect(actions.append)
    controller.handle_eye_status(True, True)

    controller._handle_toolbar_dwell("speech", QPoint(10, 10), 1000)
    controller._handle_toolbar_dwell("speech", QPoint(10, 10), 1250)
    controller._handle_toolbar_dwell("speech", QPoint(10, 10), 1450)
    assert actions == ["speech"]

    controller.handle_eye_status(True, False)
    controller.handle_eye_status(True, True)
    controller._handle_toolbar_dwell("speech", QPoint(10, 10), 3000)
    controller._handle_toolbar_dwell("speech", QPoint(10, 10), 4000)
    assert actions == ["speech"]

    controller._reset_toolbar_dwell()
    controller._handle_toolbar_dwell("speech", QPoint(10, 10), 5000)
    controller._handle_toolbar_dwell("speech", QPoint(10, 10), 5250)
    controller._handle_toolbar_dwell("speech", QPoint(10, 10), 5450)
    assert actions == ["speech", "speech"]


def test_cancel_toolbar_interaction_clears_dwell_and_gaze_feedback():
    controller = make_controller()
    gaze_targets = []
    controller.toolbar_gaze_target_changed.connect(gaze_targets.append)
    controller._handle_toolbar_dwell("speech", QPoint(10, 10), 1000)
    controller._handle_toolbar_dwell("speech", QPoint(10, 10), 1500)

    controller.cancel_toolbar_interaction()

    assert controller._toolbar_gaze_target is None
    assert gaze_targets == ["speech", None]


def test_mouse_action_cancels_pending_desktop_dwell_until_gaze_moves_away():
    controller = make_controller()
    controller.update_settings(
        GazeSettings(dwell_ms=200, click_cooldown_ms=100, use_precision_zoom=True)
    )
    controller.set_mode(LEFT_CLICK)
    target = GazeScreenPoint(QPoint(30, 40), QPoint(130, 240))
    moved_target = GazeScreenPoint(QPoint(100, 120), QPoint(200, 320))
    requested = []
    controller.click_zoom_requested.connect(lambda point: requested.append(QPoint(point)))

    controller._handle_target_dwell(target, 1000)
    controller._handle_target_dwell(target, 1500)
    controller.cancel_gaze_interactions_for_mouse()
    controller._handle_target_dwell(target, 3000)

    assert requested == []

    controller._handle_target_dwell(moved_target, 3100)
    controller._handle_target_dwell(moved_target, 3600)
    controller._handle_target_dwell(moved_target, 3800)

    assert requested == [QPoint(100, 120)]


def test_quick_actions_and_click_modes_are_mutually_exclusive():
    controller = make_controller()

    controller.set_mode(LEFT_CLICK)
    controller.set_quick_actions_enabled(True)
    assert controller.active_mode is None
    assert controller.quick_actions_enabled is True

    controller.set_mode(RIGHT_CLICK)
    assert controller.quick_actions_enabled is False
    assert controller.active_mode == RIGHT_CLICK
