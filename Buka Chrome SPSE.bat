@echo off
start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="D:\Dokumen\temp_edge_spse" ^
  --no-first-run ^
  --no-default-browser-check ^
  "https://spse.inaproc.id/tapinkab/"
