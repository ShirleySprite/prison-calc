# Windows standalone build

The app window and Qt application use `assets/app_icon.png`; the multi-size
`assets/app_icon.ico` is embedded into the executable so Windows Task Manager
and shortcuts can use the tombstone icon instead of the Python interpreter icon.

On Windows 10/11:

1. Extract the complete project ZIP to a writable folder.
2. Install Python and make sure `python` is available in Command Prompt.
3. Run `build_windows.bat` (it installs the dependencies listed in
   `requirements-build.txt`).
4. The standalone, windowed executable is written to `dist` with the full
   application display name.

The build includes all files under `assets` and `rendering/assets`, so adding
resources inside those folders does not require editing the batch file. For
ordinary Python source changes, just rerun `build_windows.bat`; update the build
requirements if a new third-party package is introduced. Resources placed in a
new folder need a corresponding `--add-data` entry.

The Windows build must be run on Windows; a Linux build host cannot produce a
supported Windows EXE.
