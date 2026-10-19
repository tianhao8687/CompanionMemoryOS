"""Build test-only instrumentation for the local preview signing key (no Gradle download)."""

from __future__ import annotations

import argparse
import os
import subprocess
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--keystore", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).parent / "android_probe"
    sdk, java = args.sdk.resolve(), args.java_home.resolve()
    build = sdk / "build-tools/36.0.0"
    android_jar = sdk / "platforms/android-36/android.jar"
    classes = output / "classes"
    classes.mkdir()
    dex = output / "dex"
    dex.mkdir()
    env = {**os.environ, "JAVA_HOME": str(java)}

    def run(*command: str | Path) -> None:
        subprocess.run([str(c) for c in command], check=True, env=env, timeout=120)

    manifest = output / "AndroidManifest.xml"
    manifest.write_text(
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
        'package="com.xinyu.smoke"><uses-sdk android:minSdkVersion="24" '
        'android:targetSdkVersion="36"/><instrumentation '
        'android:name="com.xinyu.smoke.NativeProbe" '
        'android:targetPackage="com.xinyu.xinyu_flutter.preview"/>'
        '<application android:label="XinYu synthetic test" android:debuggable="true">'
        '<activity android:name="com.xinyu.smoke.FixtureActivity" android:exported="true"/>'
        "</application></manifest>",
        encoding="utf-8",
    )
    run(
        java / "bin/javac.exe",
        "-source",
        "17",
        "-target",
        "17",
        "-classpath",
        android_jar,
        "-d",
        classes,
        *source.glob("*.java"),
    )
    run(
        build / "d8.bat",
        "--lib",
        android_jar,
        "--min-api",
        "24",
        "--output",
        dex,
        *classes.rglob("*.class"),
    )
    unsigned = output / "unsigned.apk"
    run(build / "aapt2.exe", "link", "-o", unsigned, "-I", android_jar, "--manifest", manifest)
    with zipfile.ZipFile(unsigned, "a", compression=zipfile.ZIP_DEFLATED) as apk:
        apk.write(dex / "classes.dex", "classes.dex")
        for asset in source.glob("*.py"):
            apk.write(asset, f"assets/{asset.name}")
    signed = output / "xinyu-native-probe.apk"
    run(build / "zipalign.exe", "-p", "4", unsigned, signed)
    run(
        build / "apksigner.bat",
        "sign",
        "--ks",
        args.keystore,
        "--ks-key-alias",
        "androiddebugkey",
        "--ks-pass",
        "pass:android",
        "--key-pass",
        "pass:android",
        signed,
    )
    run(build / "apksigner.bat", "verify", signed)
    print(signed)


if __name__ == "__main__":
    main()
