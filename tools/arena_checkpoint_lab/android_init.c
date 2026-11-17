/* PID 1 preparation for the existing Waydroid Android images inside KVM.
 * All mounts/devices/compositor processes are guest-local. No game logic here.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/ioctl.h>
#include <linux/android/binderfs.h>
#include <sched.h>

static void fail(const char *what) { perror(what); for (;;) sleep(10); }
static void directory(const char *path, mode_t mode) {
    if (mkdir(path,mode)<0 && errno!=EEXIST) fail(path);
}
static void mount_at(const char *source,const char *target,const char *type,unsigned long flags,const char *data) {
    if (mount(source,target,type,flags,data)<0) fail(target);
}
static void module(const char *path) {
    int fd=open(path,O_RDONLY);
    if (fd<0 || syscall(SYS_finit_module,fd,"",0)<0) fail(path);
    close(fd);
}
static void bind(const char *source,const char *target) {
    mount_at(source,target,NULL,MS_BIND|MS_REC,NULL);
}
int main(void) {
    directory("/dev",0755); directory("/proc",0755); directory("/sys",0755);
    mount_at("devtmpfs","/dev","devtmpfs",0,NULL);
    int console=open("/dev/console",O_RDWR);
    if (console>=0) { dup2(console,0); dup2(console,1); dup2(console,2); if(console>2)close(console); }
    setvbuf(stdout,NULL,_IONBF,0);
    mount_at("proc","/proc","proc",0,NULL);
    mount_at("sysfs","/sys","sysfs",0,NULL);
    mount_at(NULL,"/",NULL,MS_REC|MS_PRIVATE,NULL);
    module("/modules/virtio_mmio.ko");
    module("/modules/overlay.ko");
    module("/modules/binfmt_misc.ko");
    module("/modules/dummy.ko");
    module("/modules/nfnetlink.ko");
    module("/modules/nfnetlink_log.ko");
    module("/modules/fuse.ko");
    for (int i=0;i<200 && access("/dev/vdc",F_OK);i++) usleep(10000);
    directory("/system-lower",0755); directory("/vendor-lower",0755);
    directory("/writable",0755); directory("/sysroot",0755);
    mount_at("/dev/vda","/system-lower","ext4",MS_RDONLY,NULL);
    mount_at("/dev/vdb","/vendor-lower","ext4",MS_RDONLY,NULL);
    mount_at("/dev/vdc","/writable","ext4",0,NULL);
    directory("/writable/system-upper",0755); directory("/writable/system-work",0755);
    directory("/writable/vendor-upper",0755); directory("/writable/vendor-work",0755);
    directory("/writable/data",0771);
    mount_at("overlay","/sysroot","overlay",0,"lowerdir=/system-lower,upperdir=/writable/system-upper,workdir=/writable/system-work");
    mount_at("overlay","/sysroot/vendor","overlay",0,"lowerdir=/vendor-lower,upperdir=/writable/vendor-upper,workdir=/writable/vendor-work");
    bind("/writable/data","/sysroot/data");
    bind("/proc","/sysroot/proc"); bind("/sys","/sysroot/sys");
    directory("/dev/pts",0755);
    mount_at("devpts","/dev/pts","devpts",0,"mode=0620,ptmxmode=0666");
    directory("/sysroot/run",0755); directory("/sysroot/tmp",01777); directory("/sysroot/var",0755);
    mount_at("tmpfs","/sysroot/run","tmpfs",0,NULL);
    mount_at("tmpfs","/sysroot/tmp","tmpfs",0,"mode=1777");
    mount_at("tmpfs","/sysroot/var","tmpfs",0,NULL);
    directory("/run",0755); directory("/run/xdg",0700); chown("/run/xdg",1000,1000);
    directory("/sysroot/run/xdg",0700);
    bind("/run/xdg","/sysroot/run/xdg");
    directory("/diag",0755); directory("/sysroot/checkpoint-diag",0755);
    bind("/diag","/sysroot/checkpoint-diag");
    /* Binderfs creates guest-local endpoints; static legacy nodes are optional. */
    directory("/dev/binderfs",0755);
    mount_at("binder","/dev/binderfs","binder",0,NULL);
    int binder_control=open("/dev/binderfs/binder-control",O_RDONLY);
    if (binder_control<0) fail("binder-control");
    const char *names[]={"binder","hwbinder","vndbinder"};
    for (int i=0;i<3;i++) {
        struct binderfs_device device={0};
        strcpy(device.name,names[i]);
        char source[128],target[128];
        snprintf(source,sizeof(source),"/dev/binderfs/%s",names[i]);
        snprintf(target,sizeof(target),"/dev/%s",names[i]);
        if (access(source,F_OK)<0 && ioctl(binder_control,BINDER_CTL_ADD,&device)<0)
            fail("guest binder allocation");
        unlink(target);
        if (symlink(source,target)<0 || chmod(source,0666)<0) fail("guest binder node");
    }
    close(binder_control);
    /* Include child mounts such as binderfs/pts in Android's device tree. */
    bind("/dev","/sysroot/dev");
    if (access("/dev/vdd",F_OK)==0) {
        directory("/sysroot/checkpoint-payload",0755);
        mount_at("/dev/vdd","/sysroot/checkpoint-payload","ext4",MS_RDONLY,NULL);
    }
    directory("/sys/fs/cgroup",0755);
    directory("/sys/kernel/debug",0755);
    mount("debugfs","/sys/kernel/debug","debugfs",0,NULL);
    /* Props and translation files are explicit non-account build inputs. */
    FILE *src=fopen("/waydroid.prop","rb"),*dst=fopen("/sysroot/vendor/waydroid.prop","wb");
    if (!src || !dst) fail("guest properties");
    char buffer[4096]; size_t count;
    while ((count=fread(buffer,1,sizeof(buffer),src))) fwrite(buffer,1,count,dst);
    fclose(src); fclose(dst);
    if (!fork()) {
        if (unshare(CLONE_NEWNS)<0) fail("display mount namespace");
        int log=open("/diag/weston.log",O_CREAT|O_WRONLY|O_TRUNC,0644);
        if (log>=0) {dup2(log,1);dup2(log,2);if(log>2)close(log);}
        setenv("XDG_RUNTIME_DIR","/run/xdg",1);
        setenv("HOME","/tmp",1);
        setgid(1000); setuid(1000);
        execl("/usr/bin/weston","weston","--backend=headless","--renderer=pixman",
              "--shell=kiosk-shell.so","--no-config","--idle-time=0","--width=1280","--height=720","--socket=wayland-0",(char *)NULL);
        perror("weston"); _exit(111);
    }
    /* Agent keeps glibc already mapped, then executes Android's own shell. */
    int agent_root=open("/sysroot",O_RDONLY|O_DIRECTORY);
    if(agent_root<0)fail("pin agent root");
    if (!fork()) {
        char descriptor[32];snprintf(descriptor,sizeof(descriptor),"%d",agent_root);
        execl("/checkpoint-agent","checkpoint-agent",descriptor,(char *)NULL);
        perror("checkpoint agent"); _exit(111);
    }
    close(agent_root);
    puts("MR3A_ANDROID_MOUNTS_READY");
    /* Give Android a real namespace root so later mount namespaces and fd
       allowlists see /sys/... rather than an outside /sysroot/... alias. */
    if (chdir("/sysroot")<0 || mount("/sysroot","/",NULL,MS_MOVE,NULL)<0
        || chroot(".")<0 || chdir("/")<0) fail("Android switch root");
    setenv("PATH","/system/bin:/system/xbin:/vendor/bin",1);
    setenv("ANDROID_ROOT","/system",1);
    setenv("ANDROID_DATA","/data",1);
    /* Waydroid's own first stage creates these nodes and the /dev/socket tree. */
    unlink("/dev/kmsg"); unlink("/dev/random"); unlink("/dev/urandom");
    execl("/init","/init",(char *)NULL);
    fail("Android init");
}
