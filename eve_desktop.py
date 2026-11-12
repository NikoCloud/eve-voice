"""Launch Eve in a native desktop window (pywebview) with a system tray icon (pystray)
and global Right Ctrl hold-to-talk (pynput)."""
import sys
import eve_ui

if __name__ == "__main__":
    if "--desktop" not in sys.argv:
        sys.argv.append("--desktop")
    eve_ui.main()
