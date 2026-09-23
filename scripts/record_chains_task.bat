@echo off
REM Hourly options-surface snapshot, independent of the API server.
REM
REM WHY THIS EXISTS SEPARATELY FROM THE API JOB. The recorder was originally
REM scheduled inside api/main.py's lifespan, so it only ran while the server
REM was up. Measured 2026-09-21: 0.95 rows/hour against an expected 2.00 --
REM 48% uptime, because the server died with every session that launched it.
REM Half of the first day's data is gone and cannot be recovered; Deribit
REM serves the CURRENT chain and nobody sells back an hour nobody recorded.
REM
REM At 2 instruments (BTC/ETH are all Deribit lists) the time to a testable
REM sample is over a year on 1h bars even at perfect uptime. Halving that by
REM fixing uptime is the single cheapest improvement available to this dataset.
REM
REM Safe to run alongside the API's own job: chain_recorder dedups on a 1-hour
REM window per currency, so a second call inside the same hour is a no-op
REM rather than a duplicate row.

setlocal
set ROOT=C:\Users\wayka\OneDrive\Documents\TIS
set PY=%ROOT%\project_titan_x\.venv\Scripts\python.exe
set SCRIPT=%ROOT%\project_titan_x\scripts\record_option_chains.py
set LOG=%ROOT%\project_titan_x\logs\chain_recorder.log

"%PY%" "%SCRIPT%" >> "%LOG%" 2>&1
endlocal
