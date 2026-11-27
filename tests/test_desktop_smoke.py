"""Regression tests for native desktop display acceptance."""

import ctypes

from tools import desktop_smoke


def test_linux_window_id_matches_xwininfo_tree_entry():
    tree = '0x50d (the root window) (has no name)\n  0x200003 "Local AI Hub": ("local-ai-hub-desktop" "local-ai-hub-desktop") 1200x760+0+0  +0+0\n'

    parser = getattr(desktop_smoke, "_linux_window_id", None)

    assert callable(parser)
    assert parser(tree) == "0x200003"


def test_windows_handle_comparison_uses_numeric_handle_values():
    matcher = getattr(desktop_smoke, "_same_windows_handle", None)

    assert callable(matcher)
    assert matcher(ctypes.c_void_p(0x1234), ctypes.c_void_p(0x1234))
    assert not matcher(ctypes.c_void_p(0x1234), ctypes.c_void_p(0x5678))
