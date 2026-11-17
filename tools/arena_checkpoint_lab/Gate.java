package dev.mr3a.checkpoint;

/** Guest-local JNI exchange; the VM stops inside the calling Unity thread. */
public final class Gate {
    public native String exchange(String state);
}
