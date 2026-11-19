package dev.mr3a.arena.capture;

import android.graphics.Bitmap;
import android.os.Build;
import android.os.IBinder;
import android.os.Process;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.KeyCharacterMap;
import android.view.KeyEvent;
import java.io.BufferedOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.net.ServerSocket;
import java.net.Socket;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

/** Android pixels, explicit key pulses and opt-in local paired collection. */
public final class FrameServer {
    static final int KEY_PULSE_MS = 80;
    static final int SLIDE_HOLD_MS = 500;
    private static final int VERSION = 1;
    private static final int MAX_LABELS = 8 * 1024 * 1024;
    private static final File CONTROL = new File("/sdcard/Android/data/com.pandadastudio.ninjamustdie3/files/arena-control");

    private static JSONObject readJson(File file) throws Exception {
        long length = file.length();
        if (!file.exists() || length == 0) return null;
        if (length > MAX_LABELS) throw new IOException("Native label file exceeds its bound");
        byte[] data = new byte[(int) length];
        try (DataInputStream input = new DataInputStream(new FileInputStream(file))) {
            input.readFully(data);
        } catch (EOFException partial) { return null; }
        try { return new JSONObject(new String(data, "UTF-8")); }
        catch (org.json.JSONException partial) { return null; }
    }

    private static byte[] pairedStep(int ticks, int action, String identity) throws Exception {
        if (ticks < 1 || ticks > 10 || action < 0 || action > 2) {
            throw new IOException("Invalid native paired step");
        }
        String name = action == 0 ? "none" : action == 1 ? "jump" : "down";
        File command = new File(CONTROL, "command.json");
        File temporary = new File(CONTROL, "command-" + identity + ".tmp");
        if (command.exists()) throw new IOException("Native command slot is occupied");
        JSONObject request = new JSONObject();
        request.put("id", identity);
        request.put("code", "return MR3A.paired_step(" + ticks + ",\"" + name + "\",\"" + identity + "\")");
        try (FileOutputStream output = new FileOutputStream(temporary)) {
            output.write(request.toString().getBytes("UTF-8"));
        }
        if (!temporary.renameTo(command)) {
            temporary.delete();
            throw new IOException("Cannot publish native paired command");
        }
        long deadline = SystemClock.elapsedRealtime() + 8000;
        boolean acknowledged = false;
        try {
            while (SystemClock.elapsedRealtime() < deadline) {
                JSONObject response = readJson(new File(CONTROL, "result.json"));
                if (response != null && identity.equals(response.optString("id"))) {
                    acknowledged = true;
                    if (!command.delete() && command.exists()) throw new IOException("Cannot clear acknowledged command");
                    if (!response.optBoolean("ok")) throw new IOException(response.optString("error"));
                    break;
                }
                Thread.sleep(1);
            }
        } finally {
            if (!acknowledged) command.delete();
        }
        if (!acknowledged) throw new IOException("Native paired command was not acknowledged");
        while (SystemClock.elapsedRealtime() < deadline) {
            JSONObject result = readJson(new File(CONTROL, "paired-collection.json"));
            if (result != null && identity.equals(result.optString("identity")) && result.optBoolean("done")) {
                if (!result.isNull("error") && !result.optString("error").isEmpty()) {
                    throw new IOException(result.optString("error"));
                }
                if (result.optJSONObject("labels") == null) throw new IOException("Native paired labels are missing");
                return result.toString().getBytes("UTF-8");
            }
            Thread.sleep(1);
        }
        throw new IOException("Native paired step did not finish");
    }

    private static final class Keys {
        final Object manager;
        final Method inject;
        final HashMap<Integer, KeyEvent> held = new HashMap<Integer, KeyEvent>();
        final ScheduledExecutorService releases = Executors.newSingleThreadScheduledExecutor();
        Keys() throws Exception {
            Class<?> type = Class.forName("android.hardware.input.InputManager");
            manager = type.getMethod("getInstance").invoke(null);
            inject = type.getMethod("injectInputEvent", InputEvent.class, int.class);
        }
        synchronized void tap(final int code, int durationMs) throws Exception {
            if (held.containsKey(code)) return;
            long now = SystemClock.uptimeMillis();
            KeyEvent event = new KeyEvent(now, now, KeyEvent.ACTION_DOWN, code, 0, 0,
                    KeyCharacterMap.VIRTUAL_KEYBOARD, 0, 0, InputDevice.SOURCE_KEYBOARD);
            if (!Boolean.TRUE.equals(inject.invoke(manager, event, 0))) {
                throw new IOException("Keyboard injection was rejected");
            }
            held.put(code, event);
            releases.schedule(new Runnable() {
                public void run() {
                    try { release(code); } catch (Exception error) { error.printStackTrace(System.err); }
                }
            }, durationMs, TimeUnit.MILLISECONDS);
        }
        synchronized void release(int code) throws Exception {
            KeyEvent event = held.get(code);
            if (event != null) {
                KeyEvent up = new KeyEvent(event.getDownTime(), SystemClock.uptimeMillis(),
                        KeyEvent.ACTION_UP, code, 0, event.getMetaState(), event.getDeviceId(),
                        event.getScanCode(), event.getFlags(), event.getSource());
                if (!Boolean.TRUE.equals(inject.invoke(manager, up, 0))) {
                    throw new IOException("Keyboard release was rejected");
                }
                held.remove(code);
            }
        }
        synchronized void close() throws Exception {
            releases.shutdownNow();
            Exception failure = null;
            for (Integer code : held.keySet().toArray(new Integer[0])) {
                try { release(code); } catch (Exception error) { if (failure == null) failure = error; }
            }
            if (failure != null) throw failure;
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 3) throw new IllegalArgumentException("width height session-token required");
        int width = Integer.parseInt(args[0]), height = Integer.parseInt(args[1]);
        if (width < 16 || height < 16 || width > 4096 || height > 4096
                || (long) width * height > 4194304 || !args[2].matches("[0-9a-f]{32}")) {
            throw new IllegalArgumentException("Invalid capture dimensions or session token");
        }
        // This backend deliberately supports the installed Android 13 API.
        if (Build.VERSION.SDK_INT != 33) throw new IOException("Capture backend requires Android API 33");
        Class<?> sc = Class.forName("android.view.SurfaceControl");
        Class<?> builderClass = Class.forName("android.view.SurfaceControl$DisplayCaptureArgs$Builder");
        Class<?> argsClass = Class.forName("android.view.SurfaceControl$DisplayCaptureArgs");
        Class<?> shotClass = Class.forName("android.view.SurfaceControl$ScreenshotHardwareBuffer");
        IBinder display = (IBinder) sc.getMethod("getInternalDisplayToken").invoke(null);
        if (display == null) throw new IOException("No internal Android display");
        Object builder = builderClass.getConstructor(IBinder.class).newInstance(display);
        builderClass.getMethod("setSize", int.class, int.class).invoke(builder, width, height);
        Object captureArgs = builderClass.getMethod("build").invoke(builder);
        Method capture = sc.getMethod("captureDisplay", argsClass);
        Method asBitmap = shotClass.getMethod("asBitmap");
        Method getBuffer = shotClass.getMethod("getHardwareBuffer");
        Method closeBuffer = Class.forName("android.hardware.HardwareBuffer").getMethod("close");
        byte[] pixels = new byte[width * height * 4];
        ByteBuffer buffer = ByteBuffer.wrap(pixels);
        // ADB is only the lifecycle/control pipe. Pixel traffic uses the named
        // device's direct local data channel to avoid ADB shell packet latency.
        ServerSocket listener = new ServerSocket(0, 1);
        listener.setSoTimeout(5000);
        DataOutputStream hello = new DataOutputStream(System.out);
        hello.writeInt(0x4d523348); // MR3H
        hello.writeInt(VERSION);
        hello.writeInt(Build.VERSION.SDK_INT);
        hello.writeInt(Process.myPid());
        hello.writeInt(listener.getLocalPort());
        hello.flush();
        Socket socket;
        try { socket = listener.accept(); } finally { listener.close(); }
        socket.setTcpNoDelay(true);
        socket.setSoTimeout(30000);
        DataInputStream in = new DataInputStream(socket.getInputStream());
        DataOutputStream out = new DataOutputStream(new BufferedOutputStream(socket.getOutputStream(), 1048576));
        byte[] token = new byte[32];
        in.readFully(token);
        if (!MessageDigest.isEqual(token, args[2].getBytes("US-ASCII"))) {
            socket.close();
            throw new IOException("Capture session token mismatch");
        }
        out.writeInt(0x4d523341); // MR3A
        out.flush();
        Keys keys = null;
        try {
            while (true) {
                int command;
                try { command = in.readInt(); } catch (EOFException end) { break; }
                long sequence = in.readLong();
                if (command == 0) break;
                if (command < 1 || command > 7) throw new IOException("Unknown capture command");
                long start = System.nanoTime(), captured = start, ready = start;
                byte[] labels = null;
                if (command == 7) {
                    int ticks = in.readInt(), action = in.readInt();
                    String identity = args[2] + String.format(java.util.Locale.ROOT, "%016x", sequence);
                    labels = pairedStep(ticks, action, identity);
                }
                boolean image = command == 1 || command == 7;
                if (image) {
                    Object shot = capture.invoke(null, captureArgs);
                    captured = System.nanoTime();
                    if (shot == null) throw new IOException("Display capture returned null");
                    Object hardware = getBuffer.invoke(shot);
                    Bitmap gpu = null, cpu = null;
                    try {
                        gpu = (Bitmap) asBitmap.invoke(shot);
                        if (gpu == null) throw new IOException("Captured buffer has no bitmap");
                        cpu = gpu.copy(Bitmap.Config.ARGB_8888, false);
                        if (cpu == null || cpu.getWidth() != width || cpu.getHeight() != height
                                || cpu.getRowBytes() != width * 4) {
                            throw new IOException("Captured bitmap dimensions changed");
                        }
                        buffer.clear();
                        cpu.copyPixelsToBuffer(buffer);
                        ready = System.nanoTime();
                    } finally {
                        if (cpu != null) cpu.recycle();
                        if (gpu != null) gpu.recycle();
                        if (hardware != null) closeBuffer.invoke(hardware);
                    }
                } else if (command >= 3) {
                    if (keys == null) keys = new Keys();
                    keys.tap(command == 3 ? KeyEvent.KEYCODE_K
                            : command == 4 || command == 6 ? KeyEvent.KEYCODE_S : KeyEvent.KEYCODE_P,
                            command == 6 ? SLIDE_HOLD_MS : KEY_PULSE_MS);
                    captured = ready = System.nanoTime();
                }
                out.writeInt(0x4d523346); // MR3F
                out.writeInt(VERSION);
                out.writeInt(command);
                out.writeInt(image ? width : 0);
                out.writeInt(image ? height : 0);
                out.writeInt(image ? pixels.length : 0);
                out.writeLong(sequence);
                out.writeLong(start);
                out.writeLong(captured);
                out.writeLong(ready);
                if (image) out.write(pixels);
                if (labels != null) { out.writeInt(labels.length); out.write(labels); }
                out.flush();
            }
        } finally {
            try { if (keys != null) keys.close(); } finally { socket.close(); }
        }
    }
}
