# Api Routen abrufen - Tutorial

## Android Debugger Bridge (adb.exe)
1. Android Studio & dessen Commandline-Tools installieren
2. Neues Gerät anlegen (Android Version möglichst neu) **Google APIs**, **nicht** *Google Play Store* Version!
3. Emulator Starten
4. APK (oder Split APKs) herunterladen und mit adb auf Emulator verschieben:
```cmd
adb.exe push <APKs> /data/local/tmp
```
5. APKs installieren:
```bash
PS C:\Users\Florian> adb shell
emu64xa:/ # pm install com_sunbooster_app_vv1.1.0.apk  config.arm64_v8a.apk  config.en.apk  config.xhdpi.apk
```
6. Frida Server Datei auch draufschieben und starten:
```bash
PS C:\Users\Florian\Downloads> adb push frida-server /data/local/tmp
PS C:\Users\Florian\Downloads> adb shell
emu64xa:/ # cd /data/local/tmp
emu64xa:/data/local/tmp # ls
com_sunbooster_app_vv1.1.0.apk  config.arm64_v8a.apk  config.en.apk  config.xhdpi.apk  frida-server
emu64xa:/data/local/tmp # chmod +x frida-server
emu64xa:/data/local/tmp # /data/local/tmp/frida-server &
[1] 9729
```

## Frida
1. App lokal so starten (nicht im Emulator öffnen, der Befehl macht das!):
```bash
frida -U --codeshare akabe1/frida-multiple-unpinning -f com.sunbooster.app
```