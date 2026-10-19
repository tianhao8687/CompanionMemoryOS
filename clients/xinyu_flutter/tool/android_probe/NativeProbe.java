package com.xinyu.smoke;

import android.app.Instrumentation;
import android.os.Build;
import android.os.Bundle;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;

/** Test-only instrumentation, signed with the local preview key. Never shipped in XinYu. */
public final class NativeProbe extends Instrumentation {
    private Bundle arguments;

    @Override public void onCreate(Bundle values) {
        arguments = values;
        start();
    }

    @Override public void onStart() {
        Bundle output = new Bundle();
        try {
            if (!getTargetContext().getPackageName().equals("com.xinyu.xinyu_flutter.preview")
                    || !(Build.HARDWARE.equals("ranchu") || Build.HARDWARE.equals("goldfish"))
                    || !arguments.getString("run_id", "").matches("android-local-[a-f0-9]{32}")) {
                throw new IllegalStateException("Only an owned synthetic preview emulator is supported");
            }
            String phase = arguments.getString("phase", "base");
            if (phase.equals("sensor_metadata")) {
                android.hardware.SensorManager sensors = (android.hardware.SensorManager)
                    getTargetContext().getSystemService(android.content.Context.SENSOR_SERVICE);
                org.json.JSONObject metadata = new org.json.JSONObject();
                for (int type : new int[]{android.hardware.Sensor.TYPE_LIGHT, android.hardware.Sensor.TYPE_PROXIMITY}) {
                    android.hardware.Sensor sensor = sensors.getDefaultSensor(type);
                    org.json.JSONObject item = new org.json.JSONObject();
                    item.put("available", sensor != null);
                    if (sensor != null) item.put("maximum_range", sensor.getMaximumRange()).put("name", sensor.getName());
                    metadata.put(type == android.hardware.Sensor.TYPE_LIGHT ? "light" : "proximity", item);
                }
                output.putString("report", metadata.toString());
                finish(-1, output);
                return;
            }
            if (phase.equals("granted") || phase.equals("command")) {
                // am instrument restarts the target process. Rebind its service
                // after that restart; do not suppress other accessibility services.
                shell("settings delete secure enabled_accessibility_services");
                shell("settings put secure enabled_accessibility_services "
                    + "com.xinyu.xinyu_flutter.preview/com.xinyu.xinyu_flutter.PhoneAccessibilityService");
                shell("settings put secure accessibility_enabled 1");
            }
            if (arguments.getString("foreground", "0").equals("1")) {
                android.content.Intent launch = getTargetContext().getPackageManager()
                    .getLaunchIntentForPackage(getTargetContext().getPackageName());
                if (launch == null) throw new IllegalStateException("Missing preview activity");
                launch.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivitySync(launch);
                android.os.SystemClock.sleep(1500);
            }
            ClassLoader loader = getTargetContext().getClassLoader();
            if (phase.equals("native_music")) {
                // Runs the installed APK's actual MediaSession implementation
                // when an older emulator cannot translate the Python runtime.
                // Deliberately separate from command: this is not a Python/MCP pass.
                org.json.JSONObject request = new org.json.JSONObject(arguments.getString("request", "{}"));
                String tool = request.getString("tool");
                if (!java.util.Arrays.asList("netease_status", "netease_playback_state", "netease_control", "netease_seek").contains(tool)) {
                    throw new IllegalArgumentException("Unsupported native-only test operation");
                }
                org.json.JSONObject params = request.optJSONObject("arguments");
                Object response = Class.forName("com.xinyu.xinyu_flutter.MusicBridge", true, loader)
                    .getMethod("call", android.content.Context.class, String.class, String.class)
                    .invoke(null, getTargetContext(), tool, params == null ? "{}" : params.toString());
                output.putString("report", response.toString());
                finish(-1, output);
                return;
            }
            Class<?> python = Class.forName("com.chaquo.python.Python", true, loader);
            if (!(Boolean) python.getMethod("isStarted").invoke(null)) {
                Object platform = Class.forName("com.chaquo.python.android.AndroidPlatform", true, loader)
                    .getConstructor(android.content.Context.class).newInstance(getTargetContext());
                python.getMethod("start", Class.forName("com.chaquo.python.Python$Platform", true, loader))
                    .invoke(null, platform);
            }
            Object instance = python.getMethod("getInstance").invoke(null);
            Object builtins = python.getMethod("getModule", String.class).invoke(instance, "builtins");
            Method call = builtins.getClass().getMethod("callAttr", String.class, Object[].class);
            call.invoke(builtins, "setattr", new Object[]{builtins, "_xinyu_smoke_context", getTargetContext()});
            call.invoke(builtins, "setattr", new Object[]{builtins, "_xinyu_smoke_phase", arguments.getString("phase", "base")});
            call.invoke(builtins, "setattr", new Object[]{builtins, "_xinyu_smoke_run", arguments.getString("run_id")});
            call.invoke(builtins, "setattr", new Object[]{builtins, "_xinyu_smoke_request", arguments.getString("request", "{}")});
            String source;
            String asset = phase.equals("screen_companion") ? "screen_companion_probe.py"
                : phase.equals("command") ? "command_probe.py" : "native_probe.py";
            try (java.io.InputStream input = getContext().getAssets().open(asset)) {
                java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
                byte[] buffer = new byte[8192];
                int count;
                while ((count = input.read(buffer)) >= 0) bytes.write(buffer, 0, count);
                source = new String(bytes.toByteArray(), StandardCharsets.UTF_8);
            }
            Object globals = call.invoke(builtins, "dict", new Object[]{});
            call.invoke(builtins, "exec", new Object[]{source, globals, globals});
            Object report = call.invoke(builtins, "getattr", new Object[]{builtins, "_xinyu_smoke_result"});
            output.putString("report", report.toString());
            finish(-1, output);
        } catch (Throwable error) {
            java.io.StringWriter writer = new java.io.StringWriter();
            error.printStackTrace(new java.io.PrintWriter(writer));
            output.putString("probe_error", writer.toString());
            finish(1, output);
        }
    }

    private void shell(String command) throws java.io.IOException {
        try (android.os.ParcelFileDescriptor fd = getUiAutomation(1).executeShellCommand(command);
             java.io.InputStream stream = new android.os.ParcelFileDescriptor.AutoCloseInputStream(fd)) {
            byte[] buffer = new byte[1024];
            while (stream.read(buffer) >= 0) { }
        }
    }
}
