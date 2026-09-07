@echo off
rem Imports every PDF in data\finance\shakepay\ (or the folder passed as
rem the first argument) into data\finance\finance.db - see
rem finance/README.md's "Shakepay: PDF import" section.
rem
rem Uses %~dp0 (this .bat file's own folder) to build the script path, so
rem it works no matter what directory it's run from - a plain relative
rem path like "finance\import_shakepay.py" only resolves correctly if the
rem current directory happens to already be backend\.

set PYTHON="C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
set SHAKEPAY_DIR=%~dp0..\data\finance\shakepay
if not "%~1"=="" set SHAKEPAY_DIR=%~1

%PYTHON% "%~dp0finance\import_shakepay.py" "%SHAKEPAY_DIR%"
pause
