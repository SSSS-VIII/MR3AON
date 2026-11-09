package dev.mr3a.arena.capture;

import android.graphics.Bitmap;
import android.os.Build;
import android.os.IBinder;
import android.os.Process;
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

/** Android-side capture only. No game injection, desktop API, codec or input events. */
public final class FrameServer {
    private static final int VERSION = 1;

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
        try {
            while (true) {
                int command;
                try { command = in.readInt(); } catch (EOFException end) { break; }
                long sequence = in.readLong();
                if (command == 0) break;
                if (command != 1 && command != 2) throw new IOException("Unknown capture command");
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
        } finally { socket.close(); }
    }
}
