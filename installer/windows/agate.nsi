; Agate Loader - instalador para Windows (NSIS).
;
; Sigue el mismo esquema que el instalador oficial de Geode: valida la carpeta del juego buscando
; libcocos2d.dll, descomprime los ficheros del loader (Geode.dll + proxy XInput1_4.dll ...) junto a
; GeometryDash.exe y deja todo dentro de la carpeta del juego. Añade lo propio de Agate:
;   <juego>\agate\agate-autoport.exe            actualizador de mods
;   <juego>\geode\mods\agate.autoport.geode     mod que lo lanza al abrir el juego
;
; Parámetros (los pasa CI):  /DVERSION=1.0.0  /DPAYLOAD_DIR=...\payload\win
;   /DAUTOPORT_EXE=...\agate-autoport.exe  /DAUTOPORT_MOD=...\agate.autoport.geode
;   /DUNINSTALL_LIST=...\uninstall-list.nsh  /DOUTFILE=...\Agate-Setup.exe

Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!ifndef OUTFILE
  !define OUTFILE "Agate-Setup.exe"
!endif

Name "Agate Loader ${VERSION}"
OutFile "${OUTFILE}"
InstallDir "$PROGRAMFILES32\Steam\steamapps\common\Geometry Dash"
RequestExecutionLevel highest
SetCompressor /SOLID lzma
ShowInstDetails show

!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgateLoader"

!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TEXT "$(T_WELCOME)"
!define MUI_DIRECTORYPAGE_TEXT_TOP "$(T_DIR_TOP)"
!define MUI_FINISHPAGE_TEXT "$(T_FINISH)"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Spanish"
!insertmacro MUI_LANGUAGE "English"

LangString T_WELCOME ${LANG_SPANISH} "Este asistente instalará el cargador de mods Agate (basado en Geode) dentro de la carpeta de Geometry Dash.$\r$\n$\r$\nCierra el juego antes de continuar."
LangString T_WELCOME ${LANG_ENGLISH} "This wizard installs the Agate mod loader (Geode-based) inside your Geometry Dash folder.$\r$\n$\r$\nClose the game before continuing."
LangString T_DIR_TOP ${LANG_SPANISH} "Indica la carpeta de Geometry Dash (la que contiene GeometryDash.exe y libcocos2d.dll). Todos los archivos se instalarán dentro de ella."
LangString T_DIR_TOP ${LANG_ENGLISH} "Choose the Geometry Dash folder (the one containing GeometryDash.exe and libcocos2d.dll). Everything is installed inside it."
LangString T_FINISH ${LANG_SPANISH} "Listo. Abre Geometry Dash desde Steam. Al iniciar, Agate revisará tus mods y actualizará los que sean de una versión anterior del juego."
LangString T_FINISH ${LANG_ENGLISH} "Done. Launch Geometry Dash from Steam. On start, Agate checks your mods and updates the ones built for an older game version."
LangString T_NOT_GD ${LANG_SPANISH} "Esa carpeta no parece contener Geometry Dash (falta libcocos2d.dll)."
LangString T_NOT_GD ${LANG_ENGLISH} "That folder does not look like Geometry Dash (libcocos2d.dll is missing)."
LangString T_RUNNING ${LANG_SPANISH} "Geometry Dash está abierto. Ciérralo y vuelve a ejecutar el instalador."
LangString T_RUNNING ${LANG_ENGLISH} "Geometry Dash is running. Close it and run the installer again."

; ------------------------------------------------------------------ detección de la carpeta
Function TryDir
  ; $0 = candidato (carpeta de Steam). Si contiene el juego, se fija como INSTDIR.
  ${If} $0 != ""
    IfFileExists "$0\steamapps\common\Geometry Dash\libcocos2d.dll" 0 +2
      StrCpy $INSTDIR "$0\steamapps\common\Geometry Dash"
  ${EndIf}
FunctionEnd

Function .onInit
  ; Orden: ruta de Steam del usuario, ruta de Steam de la máquina, ruta por defecto.
  ReadRegStr $0 HKCU "Software\Valve\Steam" "SteamPath"
  Call TryDir
  ReadRegStr $0 HKLM "SOFTWARE\WOW6432Node\Valve\Steam" "InstallPath"
  Call TryDir
  StrCpy $0 "$PROGRAMFILES32\Steam"
  Call TryDir
  ; (si Steam usa otra biblioteca, la página de directorio permite elegirla)

  ; ¿Está el juego abierto? (find devuelve 0 si encuentra el proceso)
  nsExec::ExecToStack 'cmd /c tasklist /FI "IMAGENAME eq GeometryDash.exe" /NH | find /I "GeometryDash.exe"'
  Pop $1
  Pop $2
  ${If} $1 == 0
    MessageBox MB_ICONSTOP "$(T_RUNNING)"
    Abort
  ${EndIf}
FunctionEnd

Function .onVerifyInstDir
  IfFileExists "$INSTDIR\libcocos2d.dll" +2
    Abort
FunctionEnd

; ------------------------------------------------------------------------------ instalación
Section "Agate Loader" SecMain
  ; (comprobación extra por si se saltó la validación de la página de directorio)
  IfFileExists "$INSTDIR\libcocos2d.dll" +3
    MessageBox MB_ICONSTOP "$(T_NOT_GD)"
    Abort

  DetailPrint "Instalando el loader (Geode) en $INSTDIR"
  SetOutPath "$INSTDIR"
  SetOverwrite on
  File /r "${PAYLOAD_DIR}\*.*"

  DetailPrint "Instalando el mod de auto-actualización"
  CreateDirectory "$INSTDIR\geode\mods"
  SetOutPath "$INSTDIR\geode\mods"
  File "${AUTOPORT_MOD}"

  DetailPrint "Instalando agate-autoport"
  SetOutPath "$INSTDIR\agate"
  File "${AUTOPORT_EXE}"
  WriteUninstaller "$INSTDIR\agate\uninstall-agate.exe"

  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "Agate Loader"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\agate\uninstall-agate.exe"'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

; ----------------------------------------------------------------------------- desinstalación
Section "Uninstall"
  ReadRegStr $INSTDIR HKCU "${UNINST_KEY}" "InstallLocation"
  ${If} $INSTDIR == ""
    StrCpy $INSTDIR "$EXEDIR\.."
  ${EndIf}

  ; Lista generada en CI con los ficheros del loader que se instalaron.
  !include "${UNINSTALL_LIST}"

  Delete "$INSTDIR\geode\mods\agate.autoport.geode"
  Delete "$INSTDIR\agate\agate-autoport.exe"
  RMDir /r "$INSTDIR\agate\backups"
  RMDir /r "$INSTDIR\agate\pending"
  Delete "$INSTDIR\agate\*.json"
  Delete "$INSTDIR\agate\*.log"
  Delete "$INSTDIR\agate\uninstall-agate.exe"
  RMDir "$INSTDIR\agate"
  ; Los demás mods y la carpeta geode\ NO se tocan: son datos del usuario.

  DeleteRegKey HKCU "${UNINST_KEY}"
SectionEnd
