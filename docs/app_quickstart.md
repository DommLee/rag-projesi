# App Quickstart

## One-Click Normal App (Recommended)
Use:
`100_open_desktop_app.vbs`

This launches the desktop app without showing a console window.
If packaged EXE exists, it opens EXE first; otherwise it falls back to local `pythonw` GUI.
Desktop app starts API/worker automatically on open (`Auto Start` toggle can disable this).

Alternative:
`100_open_desktop_app.bat`

## Start as Application
Use:
`100_run_app.bat`

This launches API + worker locally, seeds local fixture corpus if empty, and opens dashboard in your browser.

## Start Modern Web Application (Next.js + API)
Use:
`110_run_modern_app.bat`

This launches:
- API + worker (FastAPI backend)
- Next.js modern dashboard at `http://127.0.0.1:3000`
- live panels via SSE (`/v1/stream/metrics`, `/v1/stream/ingest`)

If you only want the web UI (assuming API already running), use:
`36_run_web_ui.bat`

## Start as Desktop GUI
Use:
`120_desktop_app.bat`

This opens a native desktop window with:
- service start/stop
- health status
- query + insight actions
- eval run button
- dashboard shortcut

## Build Desktop EXE
Use:
`130_build_desktop_exe.bat`

Output:
`releases/desktop/BISTAgenticRAGDesktop/`

## Optional Flags
- Headless test run (auto-close):  
  `100_run_app.bat --no-browser --auto-stop-seconds 10`
- Custom port:  
  `100_run_app.bat --port 18001`

## Stop Application
Use:
`101_stop_app.bat`
