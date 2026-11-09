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
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.net.ServerSocket;
import java.net.Socket;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/** Android pixels and explicit keyboard pulses. No game injection or desktop API. */
public final class FrameServer {
    private static final int VERSION = 1;

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
                if (command < 1 || command > 6) throw new IOException("Unknown capture command");
                long start = System.nanoTime(), captured = start, ready = start;
                if (command == 1) {
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
                            command == 6 ? 500 : 80);
                    captured = ready = System.nanoTime();
                }
                out.writeInt(0x4d523346); // MR3F
                out.writeInt(VERSION);
                out.writeInt(command);
                out.writeInt(command == 1 ? width : 0);
                out.writeInt(command == 1 ? height : 0);
                out.writeInt(command == 1 ? pixels.length : 0);
                out.writeLong(sequence);
                out.writeLong(start);
                out.writeLong(captured);
                out.writeLong(ready);
                if (command == 1) out.write(pixels);
                out.flush();
            }
        } finally {
            try { if (keys != null) keys.close(); } finally { socket.close(); }
        }
    }
}
