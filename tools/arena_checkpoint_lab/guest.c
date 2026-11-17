/* Synthetic Linux checkpoint fixture. This is not the arena client.
 * All state stays inside the VM: pthread/futex, stack/TLS/heap, mmap lifecycle,
 * PRNG, an unread Unix socket message, and a live file descriptor + block I/O.
 */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <pthread.h>
#include <sys/mman.h>
#include <sys/mount.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <sys/timerfd.h>
#ifdef CHECKPOINT_ANDROID_PRIMITIVES
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <linux/android/binder.h>
#include <linux/android/binderfs.h>
#endif
#ifdef CHECKPOINT_SOFTWARE_GL
#include <EGL/egl.h>
#include <GLES2/gl2.h>
#endif

#define NYX 0x6574696c2d78796eULL
#define SHARE 0x6d656d6572616873ULL
#define SNAPSHOT 0x746f687370616e73ULL
#define DONE 0x656e6f6463657865ULL
#define FAIL 0x747365746c696166ULL
#define STATE_BYTES (64UL * 1024 * 1024)
static uint64_t shared[512] __attribute__((aligned(4096)));
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t wake = PTHREAD_COND_INITIALIZER;
static pthread_cond_t finished = PTHREAD_COND_INITIALIZER;
static uint64_t worker_input, worker_result, worker_generation;
static int pending;
static const char *state_path = "/checkpoint-state";
static int binder_fd = -1;
static int timer_fd = -1;

#ifdef CHECKPOINT_SOFTWARE_GL
static EGLDisplay display;
static EGLSurface surface;
static EGLContext context;
static unsigned char pixels[128 * 128 * 4];

static void init_graphics(void);
static uint64_t draw(uint64_t rng, uint64_t step);
#endif

static void hypercall(uint64_t call, uint64_t a, uint64_t b, uint64_t c) {
    register uint64_t magic __asm__("rax") = NYX;
    register uint64_t op __asm__("r8") = call;
    register uint64_t x __asm__("r9") = a;
    register uint64_t y __asm__("r10") = b;
    register uint64_t z __asm__("r11") = c;
    __asm__ volatile("int3" : "+a"(magic), "+r"(op), "+r"(x), "+r"(y), "+r"(z)
                     : : "memory", "cc");
}

static void check(int ok, const char *message) {
    if (!ok) {
        hypercall(FAIL, (uintptr_t)message, errno, 0);
        _exit(111);
    }
}

static uint64_t mix(uint64_t value) {
    value ^= value >> 12;
    value ^= value << 25;
    value ^= value >> 27;
    return value * 2685821657736338717ULL;
}

static uint64_t monotonic_ns(void) {
    struct timespec now;
    check(clock_gettime(CLOCK_MONOTONIC, &now) == 0, "clock_gettime");
    return (uint64_t)now.tv_sec * 1000000000ULL + now.tv_nsec;
}

static uint64_t remaining_ns(void) {
    struct itimerspec timer;
    check(timerfd_gettime(timer_fd, &timer) == 0, "timerfd_gettime");
    return (uint64_t)timer.it_value.tv_sec * 1000000000ULL + timer.it_value.tv_nsec;
}

#ifdef CHECKPOINT_ANDROID_PRIMITIVES
static void init_binder(void) {
    /* All of these devices are guest-local; there is no host device passthrough. */
    int module = open("/virtio_mmio.ko", O_RDONLY);
    if (module >= 0) {
        check(syscall(SYS_finit_module, module, "", 0) == 0, "guest virtio module");
        close(module);
        mkdir("/disk", 0755);
        int mounted = 0;
        for (int i = 0; i < 200; i++) {
            if (mount("/dev/vda", "/disk", "ext4", 0, NULL) == 0) { mounted = 1; break; }
            usleep(10000);
        }
        check(mounted, "guest private ext4 block device");
        state_path = "/disk/checkpoint-state";
    }
    mkdir("/dev/binderfs", 0755);
    check(mount("binder", "/dev/binderfs", "binder", 0, NULL) == 0, "guest binderfs");
    int control = open("/dev/binderfs/binder-control", O_RDONLY);
    check(control >= 0, "binder-control");
    struct binderfs_device device = { .name = "checkpoint-binder" };
    check(ioctl(control, BINDER_CTL_ADD, &device) == 0, "BINDER_CTL_ADD");
    close(control);
    binder_fd = open("/dev/binderfs/checkpoint-binder", O_RDWR);
    check(binder_fd >= 0, "guest binder open");
    struct binder_version version;
    check(ioctl(binder_fd, BINDER_VERSION, &version) == 0, "BINDER_VERSION");
    check(version.protocol_version == BINDER_CURRENT_PROTOCOL_VERSION, "binder protocol");
    check(ioctl(binder_fd, BINDER_SET_CONTEXT_MGR, NULL) == 0, "guest binder context manager");
    shared[11] = version.protocol_version;
}
#endif

#ifdef CHECKPOINT_SOFTWARE_GL
static void init_graphics(void) {
    setenv("LIBGL_ALWAYS_SOFTWARE", "1", 1);
    setenv("GALLIUM_DRIVER", "llvmpipe", 1);
    setenv("LP_NUM_THREADS", "1", 1);
    setenv("EGL_PLATFORM", "surfaceless", 1);
    setenv("MESA_SHADER_CACHE_DISABLE", "true", 1);
    setenv("__EGL_VENDOR_LIBRARY_FILENAMES", "/egl-vendor.json", 1);
    display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    EGLint major, minor;
    check(display != EGL_NO_DISPLAY && eglInitialize(display, &major, &minor), "software EGL initialize");
    check(eglBindAPI(EGL_OPENGL_ES_API), "EGL ES API");
    const EGLint attributes[] = {
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE
    };
    EGLConfig config;
    EGLint count;
    check(eglChooseConfig(display, attributes, &config, 1, &count) && count == 1, "software EGL config");
    const EGLint size[] = { EGL_WIDTH, 128, EGL_HEIGHT, 128, EGL_NONE };
    const EGLint ctx[] = { EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE };
    surface = eglCreatePbufferSurface(display, config, size);
    context = eglCreateContext(display, config, EGL_NO_CONTEXT, ctx);
    check(surface != EGL_NO_SURFACE && context != EGL_NO_CONTEXT, "software EGL objects");
    check(eglMakeCurrent(display, surface, surface, context), "software EGL current");
    const char *renderer = (const char *)glGetString(GL_RENDERER);
    check(renderer && strstr(renderer, "llvmpipe"), "renderer must be guest software llvmpipe");
    glViewport(0, 0, 128, 128);
    shared[12] = 1;
}

static uint64_t draw(uint64_t rng, uint64_t step) {
    glDisable(GL_SCISSOR_TEST);
    glClearColor((rng & 255) / 255.f, ((rng >> 8) & 255) / 255.f, ((rng >> 16) & 255) / 255.f, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glEnable(GL_SCISSOR_TEST);
    glScissor(step % 64, (rng >> 24) % 64, 64, 64);
    glClearColor(1, 0.5f, 0.25f, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glReadPixels(0, 0, 128, 128, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    glFinish();
    check(glGetError() == GL_NO_ERROR, "software GL after restore");
    uint64_t result = 1469598103934665603ULL;
    for (size_t i = 0; i < sizeof(pixels); i++) result = (result ^ pixels[i]) * 1099511628211ULL;
    return result;
}
#endif

static void *worker(void *unused) {
    (void)unused;
    static _Thread_local uint64_t tls = 0x1438719;
    for (;;) {
        pthread_mutex_lock(&mutex);
        while (!pending) pthread_cond_wait(&wake, &mutex);
        tls = mix(tls ^ worker_input);
        worker_result = tls;
        worker_generation++;
        pending = 0;
        pthread_cond_signal(&finished);
        pthread_mutex_unlock(&mutex);
    }
    return NULL;
}

int main(void) {
    mkdir("/proc", 0755);
    mkdir("/sys", 0755);
    mkdir("/dev", 0755);
    mount("proc", "/proc", "proc", 0, NULL);
    mount("sysfs", "/sys", "sysfs", 0, NULL);
    mount("devtmpfs", "/dev", "devtmpfs", 0, NULL);
    int console = open("/dev/console", O_RDWR);
    if (console >= 0) { dup2(console, 0); dup2(console, 1); dup2(console, 2); }
    chdir("/");
    /* Materialize the BSS page before the VMM resolves its guest page tables. */
    ((volatile uint64_t *)shared)[0] = 0;
#ifdef CHECKPOINT_ANDROID_PRIMITIVES
    init_binder();
#endif
#ifdef CHECKPOINT_SOFTWARE_GL
    init_graphics();
#endif
    unsigned char *state = mmap(NULL, STATE_BYTES, PROT_READ | PROT_WRITE,
                                MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    check(state != MAP_FAILED, "initial mmap");
    memset(state, 0x35, STATE_BYTES);
    int file = open(state_path, O_CREAT | O_RDWR | O_TRUNC, 0600);
    check(file >= 0, "open checkpoint file");
    int sockets[2];
    check(socketpair(AF_UNIX, SOCK_DGRAM, 0, sockets) == 0, "socketpair");
    uint64_t queued = 0x4a17;
    check(write(sockets[0], &queued, 8) == 8, "initial socket payload");
    pthread_t thread;
    check(pthread_create(&thread, NULL, worker, NULL) == 0, "pthread_create");
    uint64_t rng = 55200, stack_counter = 0, digest = 0;
    void *allocation = NULL;
    size_t allocation_size = 0;
    char *heap = malloc(32);
    check(heap != NULL, "malloc");
    memset(heap, 0, 32);
    timer_fd = timerfd_create(CLOCK_MONOTONIC, TFD_NONBLOCK | TFD_CLOEXEC);
    check(timer_fd >= 0, "timerfd_create");
    const struct itimerspec initial_timer = { .it_value = { .tv_sec = 5 } };
    check(timerfd_settime(timer_fd, 0, &initial_timer, NULL) == 0, "arm pending timer");
    shared[14] = monotonic_ns();
    shared[15] = remaining_ns();
    hypercall(SHARE, (uintptr_t)"checkpoint-lab", (uintptr_t)shared, sizeof(shared));
    hypercall(SNAPSHOT, 0, 0, 0);
    for (;;) {
        uint64_t action = shared[0];
        size_t dirty_pages = shared[10];
        if (action == 3) {
            shared[16] = monotonic_ns();
            shared[17] = remaining_ns();
            uint64_t expired = 0;
            ssize_t got = read(timer_fd, &expired, sizeof(expired));
            check(got == 8 || (got < 0 && errno == EAGAIN), "pending timer probe");
            shared[18] = expired;
            hypercall(DONE, 0, 0, 0);
            continue;
        }
        check(action <= 2 && dirty_pages <= STATE_BYTES / 4096, "invalid input");
        stack_counter++;
        rng = mix(rng ^ action ^ stack_counter);
        for (size_t page = 0; page < dirty_pages; page++) {
            size_t index = ((page + stack_counter * 31) % (STATE_BYTES / 4096)) * 4096;
            memset(state + index, (unsigned char)(rng + page), 4096);
        }
        /* A raw user-memory copy would miss the kernel VMAs and socket queues. */
        if (allocation) check(munmap(allocation, allocation_size) == 0, "munmap");
        allocation_size = (1 + action) * 4096;
        allocation = mmap(NULL, allocation_size, PROT_READ | PROT_WRITE,
                           MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        check(allocation != MAP_FAILED, "branch mmap");
        memset(allocation, (unsigned char)rng, allocation_size);
        heap = realloc(heap, 32 + (stack_counter % 17) * 128);
        check(heap != NULL, "realloc");
        memcpy(heap, &rng, 8);
        pthread_mutex_lock(&mutex);
        worker_input = rng;
        pending = 1;
        pthread_cond_signal(&wake);
        while (pending) pthread_cond_wait(&finished, &mutex);
        pthread_mutex_unlock(&mutex);
        check(read(sockets[1], &queued, 8) == 8, "queued socket read");
        check(write(sockets[0], &rng, 8) == 8, "queued socket write");
        check(write(file, &rng, 8) == 8, "live fd append");
        check(fsync(file) == 0, "fsync");
        off_t offset = lseek(file, 0, SEEK_CUR);
        struct stat info;
        check(fstat(file, &info) == 0, "fstat");
        check(offset == (off_t)(stack_counter * 8) && info.st_size == offset,
              "file size and open fd offset after restore");
        uint64_t prior;
        check(pread(file, &prior, 8, offset - 8) == 8 && prior == rng,
              "block state after restore");
        if (stack_counter % 9 == 0) {
            pid_t child = fork();
            check(child >= 0, "fork");
            if (!child) _exit((int)(rng % 127));
            int status;
            check(waitpid(child, &status, 0) == child && WIFEXITED(status)
                  && WEXITSTATUS(status) == (int)(rng % 127), "child lifecycle");
        }
        /* Include every byte of the fixture's large mapping, not just touched pages. */
        digest = 1469598103934665603ULL;
        const uint64_t *words = (const uint64_t *)state;
        for (size_t i = 0; i < STATE_BYTES / 8; i++) digest = (digest ^ words[i]) * 1099511628211ULL;
        digest ^= mix(stack_counter) ^ mix(worker_result) ^ mix(worker_generation)
                  ^ mix(queued) ^ mix(rng) ^ mix(allocation_size) ^ mix(offset);
#ifdef CHECKPOINT_ANDROID_PRIMITIVES
        struct binder_version version;
        check(ioctl(binder_fd, BINDER_VERSION, &version) == 0
              && (uint64_t)version.protocol_version == shared[11], "binder FD after restore");
#else
        (void)binder_fd;
#endif
#ifdef CHECKPOINT_SOFTWARE_GL
        shared[13] = draw(rng, stack_counter);
        digest ^= shared[13];
#endif
        shared[1] = stack_counter;
        shared[2] = digest;
        shared[3] = worker_generation;
        shared[4] = worker_result;
        shared[5] = rng;
        shared[6] = allocation_size;
        shared[7] = offset;
        shared[8] = queued;
        shared[14] = monotonic_ns();
        shared[15] = remaining_ns();
        hypercall(DONE, 0, 0, 0);
    }
}
