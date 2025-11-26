#!/usr/bin/env python
"""
Build-Skript für GridTrader EXE-Erstellung

Verwendung:
    python build_exe.py          # Standard Build
    python build_exe.py --debug  # Mit Konsole für Debugging
    python build_exe.py --clean  # Sauberer Build (löscht vorherige)
"""

import subprocess
import sys
import shutil
from pathlib import Path


def check_pyinstaller():
    """Prüft ob PyInstaller installiert ist."""
    try:
        import PyInstaller
        print(f"PyInstaller Version: {PyInstaller.__version__}")
        return True
    except ImportError:
        print("FEHLER: PyInstaller ist nicht installiert!")
        print("Installation: pip install pyinstaller")
        return False


def clean_build():
    """Löscht vorherige Build-Artefakte."""
    project_root = Path(__file__).parent

    dirs_to_clean = ['build', 'dist']
    for dir_name in dirs_to_clean:
        dir_path = project_root / dir_name
        if dir_path.exists():
            print(f"Lösche {dir_path}...")
            shutil.rmtree(dir_path)

    # .pyc Dateien löschen
    for pyc in project_root.rglob('*.pyc'):
        pyc.unlink()

    # __pycache__ Ordner löschen
    for cache_dir in project_root.rglob('__pycache__'):
        shutil.rmtree(cache_dir)

    print("Build-Verzeichnisse bereinigt.")


def build_exe(debug=False, clean=False):
    """Erstellt die EXE-Datei."""
    project_root = Path(__file__).parent
    spec_file = project_root / 'GridTrader.spec'

    if not spec_file.exists():
        print(f"FEHLER: Spec-Datei nicht gefunden: {spec_file}")
        return False

    if clean:
        clean_build()

    # PyInstaller Befehl zusammenstellen
    cmd = [sys.executable, '-m', 'PyInstaller']

    if clean:
        cmd.append('--clean')

    cmd.append(str(spec_file))

    print(f"Starte Build: {' '.join(cmd)}")
    print("-" * 50)

    try:
        result = subprocess.run(cmd, cwd=project_root)

        if result.returncode == 0:
            exe_path = project_root / 'dist' / 'GridTrader.exe'
            if exe_path.exists():
                size_mb = exe_path.stat().st_size / (1024 * 1024)
                print("-" * 50)
                print(f"BUILD ERFOLGREICH!")
                print(f"EXE-Datei: {exe_path}")
                print(f"Dateigröße: {size_mb:.1f} MB")
                return True
            else:
                # Linux/Mac: .exe Endung nicht vorhanden
                exe_path_linux = project_root / 'dist' / 'GridTrader'
                if exe_path_linux.exists():
                    size_mb = exe_path_linux.stat().st_size / (1024 * 1024)
                    print("-" * 50)
                    print(f"BUILD ERFOLGREICH!")
                    print(f"Executable: {exe_path_linux}")
                    print(f"Dateigröße: {size_mb:.1f} MB")
                    return True

        print("BUILD FEHLGESCHLAGEN!")
        return False

    except Exception as e:
        print(f"Fehler beim Build: {e}")
        return False


def main():
    """Hauptfunktion."""
    import argparse

    parser = argparse.ArgumentParser(description='GridTrader EXE Builder')
    parser.add_argument('--debug', action='store_true',
                        help='Build mit Konsole für Debugging')
    parser.add_argument('--clean', action='store_true',
                        help='Sauberer Build (löscht vorherige Artefakte)')

    args = parser.parse_args()

    print("=" * 50)
    print("GridTrader V4.0 - EXE Builder")
    print("=" * 50)

    if not check_pyinstaller():
        sys.exit(1)

    success = build_exe(debug=args.debug, clean=args.clean)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
