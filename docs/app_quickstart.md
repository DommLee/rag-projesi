# App Quickstart

## Start as Application
Use:
`100_run_app.bat`

This launches API + worker locally, seeds local fixture corpus if empty, and opens dashboard in your browser.

## Start as Desktop GUI
Use:
`120_desktop_app.bat`

This opens a native desktop window with:
- service start/stop
- health status
- query + insight actions
- eval run button
- dashboard shortcut

## Optional Flags
- Headless test run (auto-close):  
  `100_run_app.bat --no-browser --auto-stop-seconds 10`
- Custom port:  
  `100_run_app.bat --port 18001`

## Stop Application
Use:
`101_stop_app.bat`
