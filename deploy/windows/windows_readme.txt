Running PDFXML on Windows
========================

You have a single file: pdfxml.exe. Double-click it.

- A black console window opens -- leave it open, that's the app running.
  Your browser should open to the tool automatically. If it doesn't, go
  to this address:

      http://127.0.0.1:5000

  (bookmark it -- one click next time)

- First launch only: Windows SmartScreen may say "Windows protected your
  PC" / "unknown publisher". Click "More info", then "Run anyway".

- A one-time Windows Firewall prompt may appear. Click "Allow access".
  The app only listens on your own computer; it is not exposed to the
  network.

- To stop it, close the black console window.

----------------------------------------
Building pdfxml.exe (not an end-user step): run deploy\windows\build_windows.bat
on a Windows machine with Python 3.12. See pdfxml.md, section
"A. Desktop (single user, Windows)".
