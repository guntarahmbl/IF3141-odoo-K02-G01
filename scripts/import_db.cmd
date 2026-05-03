@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_DIR=%%~fI"
set "DUMP_DIR=%PROJECT_DIR%\dump"

docker compose version >nul 2>&1
if %errorlevel%==0 (
	set "DC=docker compose"
) else (
	docker-compose --version >nul 2>&1
	if %errorlevel%==0 (
		set "DC=docker-compose"
	) else (
		echo Error: neither "docker compose" nor "docker-compose" is available.
		exit /b 1
	)
)

set "IN_FILE=%~1"
if "%IN_FILE%"=="" (
	for /f "delims=" %%F in ('dir /b /a-d /o-n "%DUMP_DIR%\odoo_backup_*.dump" 2^>nul') do (
		set "IN_FILE=%DUMP_DIR%\%%F"
		goto :found_latest
	)
	echo No backup provided and no dump found in %DUMP_DIR%
	exit /b 1
)

:found_latest

if not exist "%IN_FILE%" (
	echo File not found: %IN_FILE%
	exit /b 1
)

set "FS_FILE=%IN_FILE:.dump=_filestore.tar.gz%"

pushd "%PROJECT_DIR%" || exit /b 1

echo Stopping web container...
%DC% stop web || goto :error

echo Starting db container...
%DC% up -d db || goto :error

echo Waiting for db to be ready...
:wait_db
%DC% exec -T db pg_isready -U odoo >nul 2>nul
if errorlevel 1 (
	timeout /t 1 /nobreak >nul
	goto :wait_db
)

echo Recreating database...
%DC% exec -T db dropdb -U odoo --if-exists postgres || goto :error
%DC% exec -T db createdb -U odoo postgres || goto :error

echo Restoring database from: %IN_FILE%
%DC% exec -T db pg_restore -U odoo -d postgres --no-owner < "%IN_FILE%" || goto :error

if exist "%FS_FILE%" (
	echo Restoring filestore from: %FS_FILE%
	%DC% run --rm -T -v odoo-web-data:/filestore alpine sh -c "rm -rf /filestore/* && tar xzf - -C /filestore" < "%FS_FILE%" || goto :error
) else (
	echo Warning: No filestore backup found at %FS_FILE%, skipping.
)

echo Starting full stack...
%DC% up -d || goto :error

echo Done. Database imported.
popd
exit /b 0

:error
echo Import failed.
popd
exit /b 1
