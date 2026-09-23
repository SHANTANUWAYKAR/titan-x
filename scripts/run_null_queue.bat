@echo off
REM Remaining null campaigns, run to completion regardless of whether any
REM Claude session is alive.
REM
REM WHY A SCHEDULED TASK AND NOT A BACKGROUND SHELL. A backgrounded command
REM dies with the session that launched it. That happened three times on
REM 2026-09-20/21 -- the re-sweep died twice mid-run and the API three times.
REM Every campaign here checkpoints per path and takes --resume, so a task that
REM is killed and re-fired simply continues rather than restarting.
REM
REM Sequential on purpose: 6 parallel workers exhausted this machine's 16GB and
REM left orphaned processes behind. 3 workers per campaign, one campaign at a
REM time.

setlocal
set ROOT=C:\Users\wayka\OneDrive\Documents\TIS
set PY=%ROOT%\project_titan_x\.venv\Scripts\python.exe
set NULL=%ROOT%\project_titan_x\research\synthetic_null.py
set LOG=%ROOT%\project_titan_x\logs\null_queue.log

echo ==== null queue started %DATE% %TIME% ==== >> "%LOG%"

REM GOLD 1h was mid-run when this was created; --resume picks up its
REM checkpoint instead of discarding the paths already computed.
"%PY%" "%NULL%" --symbol GC=F --timeframe 1h --paths 50 --workers 3 --resume >> "%LOG%" 2>&1
echo ---- GC=F 1h done %TIME% >> "%LOG%"

"%PY%" "%NULL%" --symbol GC=F --timeframe 4h --paths 50 --workers 3 --resume >> "%LOG%" 2>&1
echo ---- GC=F 4h done %TIME% >> "%LOG%"

"%PY%" "%NULL%" --symbol CL=F --timeframe 1h --paths 50 --workers 3 --resume >> "%LOG%" 2>&1
echo ---- CL=F 1h done %TIME% >> "%LOG%"

echo ==== null queue finished %DATE% %TIME% ==== >> "%LOG%"
endlocal
