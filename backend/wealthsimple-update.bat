@echo off
rem Imports every CSV in data\finance\wealthsimple\ (or the folder passed
rem as the first argument) into data\finance\finance.db - see
rem finance/ARCHITECTURE.md Part A2 for the two export formats accepted
rem (credit card activity, bank/chequing activity) and finance/README.md
rem for the "Import CSV Export" flow this is the command-line equivalent
rem of.
rem
rem Uses %~dp0 (this .bat file's own folder) to build script paths, so
rem it works no matter what directory it's run from - a plain relative
rem path like "finance\import_csv.py" only resolves correctly if the
rem current directory happens to already be backend\.

set PYTHON="C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
set WEALTHSIMPLE_DIR=%~dp0..\data\finance\wealthsimple
if not "%~1"=="" set WEALTHSIMPLE_DIR=%~1

%PYTHON% "%~dp0finance\import_csv.py" "%WEALTHSIMPLE_DIR%"
pause
