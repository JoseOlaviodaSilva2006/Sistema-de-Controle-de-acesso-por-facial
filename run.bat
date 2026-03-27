@echo off
chcp 65001 > nul
setlocal
set "APP_HOME=%~dp0"
set "RUNTIME_DIR=C:\SistemaDeControleDeAcesso"

if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"
if not exist "%RUNTIME_DIR%\data" mkdir "%RUNTIME_DIR%\data"

copy /Y "%APP_HOME%access-control-system-1.0-SNAPSHOT-jar-with-dependencies.jar" "%RUNTIME_DIR%\" > nul
copy /Y "%APP_HOME%access_control.db" "%RUNTIME_DIR%\" > nul
copy /Y "%APP_HOME%data\haarcascade_frontalface_alt.xml" "%RUNTIME_DIR%\data\" > nul

cd /d "%RUNTIME_DIR%"
java --enable-native-access=ALL-UNNAMED -Dfile.encoding=UTF-8 -jar "access-control-system-1.0-SNAPSHOT-jar-with-dependencies.jar"
endlocal
pause