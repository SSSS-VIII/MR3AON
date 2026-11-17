/* Guest-local command transport. The hypercall is handled by the named VM worker.
 * No ADB, TCP connection, or host filesystem is visible to this process.
 */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <errno.h>
#include <sched.h>
static int proc_fd=-1;

static int enter_android_mounts(void) {
    int fd=openat(proc_fd,"1/ns/mnt",O_RDONLY|O_CLOEXEC);
    int root=openat(proc_fd,"1/root",O_PATH|O_DIRECTORY|O_CLOEXEC);
    if(fd<0 || root<0){if(fd>=0)close(fd);if(root>=0)close(root);return -1;}
    int result=setns(fd,CLONE_NEWNS);
    int error=errno;
    close(fd);
    if(result<0){close(root);errno=error;return -1;}
    result=fchdir(root);
    if(result==0)result=chroot(".");
    if(result==0)result=chdir("/");
    error=errno;
    close(root);
    if(result<0){errno=error;return -1;}
    return 0;
}

struct mailbox {
    uint32_t request, response;
    int32_t exit_code;
    uint32_t length;
    char command[4096];
    char output[262144];
};
static struct mailbox box __attribute__((aligned(4096)));

static void hypercall(uint64_t call, uint64_t a, uint64_t b, uint64_t c) {
    register uint64_t magic __asm__("rax") = 0x6574696c2d78796eULL;
    register uint64_t op __asm__("r8") = call;
    register uint64_t x __asm__("r9") = a;
    register uint64_t y __asm__("r10") = b;
    register uint64_t z __asm__("r11") = c;
    __asm__ volatile("int3" : "+a"(magic), "+r"(op), "+r"(x), "+r"(y), "+r"(z) : : "memory", "cc");
}

int main(int argc,char **argv) {
    if(argc!=2)return 111;
    int root_fd=atoi(argv[1]);
    if(root_fd<3 || fchdir(root_fd)<0 || chroot(".")<0 || chdir("/")<0)return 111;
    close(root_fd);
    proc_fd=open("/proc",O_RDONLY|O_DIRECTORY|O_CLOEXEC);
    if(proc_fd<0)return 111;
    setenv("PATH","/system/bin:/system/xbin:/vendor/bin",1);
    setenv("ANDROID_ROOT","/system",1);
    setenv("ANDROID_DATA","/data",1);
    for (size_t i=0;i<sizeof(box);i+=4096) ((volatile char *)&box)[i]=0;
    hypercall(0x6d656d6572616873ULL,(uintptr_t)"arena-agent",(uintptr_t)&box,sizeof(box));
    for (;;) {
        if (((volatile struct mailbox *)&box)->request != box.response) {
            uint32_t identifier=box.request;
            box.command[sizeof(box.command)-1]=0;
            uint32_t incoming=box.length;
            if(enter_android_mounts()<0) {
                box.exit_code=1;
                box.length=snprintf(box.output,sizeof(box.output),"mount namespace: %s",strerror(errno));
                box.response=identifier;
                hypercall(0x656e6f6463657865ULL,0,0,0);
                continue;
            }
            if(!strcmp(box.command,"@status")) {
                char mine[128]={0},init[128]={0};
                readlink("/proc/self/ns/mnt",mine,sizeof(mine)-1);
                readlink("/proc/1/ns/mnt",init,sizeof(init)-1);
                box.length=snprintf(box.output,sizeof(box.output),"pid=%d self=%s init=%s shell=%d runtime=%d",
                    getpid(),mine,init,access("/bin/sh",X_OK),access("/apex/com.android.runtime/bin/linker64",X_OK));
                box.exit_code=0;box.response=identifier;
                hypercall(0x656e6f6463657865ULL,0,0,0);
                continue;
            }
            if (!strncmp(box.command,"@write ",7)) {
                char path[1024]; unsigned long long offset;
                int valid=sscanf(box.command+7,"%1023s %llu",path,&offset)==2 && incoming<=sizeof(box.output);
                int fd=valid?open(path,O_WRONLY|O_CREAT|(offset==0?O_TRUNC:0),0700):-1;
                ssize_t written=fd>=0?pwrite(fd,box.output,incoming,(off_t)offset):-1;
                if(fd>=0)close(fd);
                box.exit_code=written==(ssize_t)incoming?0:1;
                box.length=snprintf(box.output,sizeof(box.output),"%zd",written);
                box.response=identifier;
                hypercall(0x656e6f6463657865ULL,0,0,0);
                continue;
            }
            box.length=0;
            FILE *pipe=popen(box.command,"r");
            if (pipe) {
                char buffer[4096];
                size_t count;
                while ((count=fread(buffer,1,sizeof(buffer),pipe))>0) {
                    size_t room=sizeof(box.output)-1-box.length;
                    size_t copied=count<room?count:room;
                    memcpy(box.output+box.length,buffer,copied);
                    box.length+=copied;
                }
                int status=pclose(pipe);
                box.exit_code=WIFEXITED(status)?WEXITSTATUS(status):-1;
                if(box.exit_code==-1 && box.length==0)
                    box.length=snprintf(box.output,sizeof(box.output),"child status=%d errno=%d (%s)",status,errno,strerror(errno));
            } else {
                box.exit_code=-1;
                box.length=snprintf(box.output,sizeof(box.output),"popen errno=%d (%s)",errno,strerror(errno));
            }
            box.output[box.length]=0;
            box.response=identifier;
            hypercall(0x656e6f6463657865ULL,0,0,0);
        }
        usleep(10000);
    }
}
