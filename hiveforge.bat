@echo off
rem ==========================================================================
rem  HiveForge - Windows (tek dosya)
rem
rem    hiveforge.bat                 Ilk calistirmada kurar, sonra kokpiti acar
rem    hiveforge.bat install         Kurulum: .venv + bagimliliklar + PATH
rem    hiveforge.bat uninstall       PATH kaydini kaldirir (--purge: verileri de siler)
rem    hiveforge.bat <komut> ...     Tum CLI komutlari: list, agents, create,
rem                                  dispatch, note, watch, logs, tools, stop ...
rem    hiveforge.bat help            Komut listesini gosterir
rem
rem  Kurulumdan sonra yeni bir terminalde dogrudan:  hiveforge <komut>
rem  Linux/macOS icin install.sh ve bin/team kullanilmaya devam eder.
rem ==========================================================================
setlocal EnableExtensions
chcp 65001 >nul
set "HF_ROOT=%~dp0"
if "%HF_ROOT:~-1%"=="\" set "HF_ROOT=%HF_ROOT:~0,-1%"
set "HF_PY=%HF_ROOT%\.venv\Scripts\python.exe"

rem Dosya Gezgini'nden cift tiklandiysa pencere sonda acik kalsin
set "HF_PAUSE="
echo %CMDCMDLINE% | find /i "%~f0" >nul && set "HF_PAUSE=1"

if /i "%~1"=="install"   ( call :install & goto :end )
if /i "%~1"=="setup"     ( call :install & goto :end )
if /i "%~1"=="uninstall" ( call :uninstall %2 & goto :end )

if not exist "%HF_PY%" (
  echo [BILGI] Ilk calistirma: HiveForge kuruluyor...
  call :install || goto :end
)
"%HF_PY%" "%HF_ROOT%\bin\hive.py" %*
goto :end


:install
echo.
echo ==================================================================
echo   HiveForge Windows Kurulumu
echo   Dizin: %HF_ROOT%
echo ==================================================================
set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE ( where python >nul 2>&1 && set "PYEXE=python" )
if not defined PYEXE (
  echo [HATA] Python bulunamadi. https://www.python.org/downloads/ adresinden Python 3.9+ kurun.
  exit /b 1
)
%PYEXE% --version
if not exist "%HF_PY%" (
  echo [1/3] Sanal ortam olusturuluyor: .venv
  %PYEXE% -m venv "%HF_ROOT%\.venv" || ( echo [HATA] venv olusturulamadi. & exit /b 1 )
) else (
  echo [1/3] Sanal ortam mevcut: .venv
)
echo [2/3] Bagimliliklar kuruluyor...
"%HF_PY%" -m pip install --upgrade pip --disable-pip-version-check -q
"%HF_PY%" -m pip install -r "%HF_ROOT%\requirements.txt" --disable-pip-version-check -q || ( echo [HATA] Bagimliliklar kurulamadi. & exit /b 1 )
echo [3/3] HiveForge klasoru kullanici PATH'ine ekleniyor...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$r = '%HF_ROOT%'; $old = $r + '\bin'; $p = [Environment]::GetEnvironmentVariable('Path','User'); if (-not $p) { $p = '' };" ^
  "$parts = @($p -split ';' | Where-Object { $_ -and $_ -ne $old });" ^
  "if ($parts -notcontains $r) { $parts += $r; Write-Host '  PATH guncellendi (yeni terminallerde gecerli).' } else { Write-Host '  PATH zaten ayarli.' };" ^
  "[Environment]::SetEnvironmentVariable('Path', ($parts -join ';'), 'User')"
echo.
echo --- CLI Motor Taramasi ---
for %%T in (agy claude codex aider ollama git) do (
  where %%T >nul 2>&1 && ( echo   [+] %%T ) || ( echo   [-] %%T bulunamadi )
)
echo.
echo   Kurulum tamamlandi. Kokpit: http://127.0.0.1:4444
echo   Yeni bir terminalde:  hiveforge          (kokpiti acar)
echo                         hiveforge help     (tum komutlar)
echo ==================================================================
exit /b 0


:uninstall
if exist "%HF_PY%" "%HF_PY%" "%HF_ROOT%\bin\hive.py" stop >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$r = '%HF_ROOT%'; $p = [Environment]::GetEnvironmentVariable('Path','User');" ^
  "if ($p) { [Environment]::SetEnvironmentVariable('Path', (($p -split ';') | Where-Object { $_ -and $_ -ne $r -and $_ -ne ($r + '\bin') }) -join ';', 'User') }"
echo [OK] PATH kaydi kaldirildi.
if /i "%~1"=="--purge" (
  if exist "%USERPROFILE%\.agy-teams" rmdir /s /q "%USERPROFILE%\.agy-teams"
  if exist "%LOCALAPPDATA%\HiveForge\agy-teams" rmdir /s /q "%LOCALAPPDATA%\HiveForge\agy-teams"
  echo [OK] HiveForge veritabani ve ayarlari silindi.
)
echo .venv klasorunu elle silebilirsiniz: %HF_ROOT%\.venv
exit /b 0


:end
set "HF_RC=%ERRORLEVEL%"
if defined HF_PAUSE pause
exit /b %HF_RC%
