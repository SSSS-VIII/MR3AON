/* Main-thread checkpoint exchange using the existing VM mailbox protocol.
 * No guest socket or timer is involved in a gameplay step. The full guest is
 * stopped at EXECDONE, including Binder, renderer threads and pending I/O.
 */
#include <jni.h>
#include <stdint.h>

struct mailbox {
    uint32_t request,response;
    int32_t exit_code;
    uint32_t length;
    char command[4096];
    char output[262144];
};
static volatile struct mailbox box __attribute__((aligned(4096)));
static int registered=0;

static void hypercall(uint64_t call,uint64_t a,uint64_t b,uint64_t c) {
    register uint64_t magic __asm__("rax")=0x6574696c2d78796eULL;
    register uint64_t op __asm__("r8")=call;
    register uint64_t x __asm__("r9")=a;
    register uint64_t y __asm__("r10")=b;
    register uint64_t z __asm__("r11")=c;
    __asm__ volatile("int3":"+a"(magic),"+r"(op),"+r"(x),"+r"(y),"+r"(z)::"memory","cc");
}

static jstring exchange(JNIEnv *env,jobject self,jstring state) {
    (void)self;
    jsize size=(*env)->GetStringUTFLength(env,state);
    if(size<0 || size>=(jsize)sizeof(box.output)) {
        jclass error=(*env)->FindClass(env,"java/lang/IllegalArgumentException");
        (*env)->ThrowNew(env,error,"Checkpoint state exceeds mailbox capacity");
        return 0;
    }
    const char *data=(*env)->GetStringUTFChars(env,state,0);
    if(!data)return 0;
    for(jsize i=0;i<size;i++)box.output[i]=data[i];
    box.output[size]=0;
    (*env)->ReleaseStringUTFChars(env,state,data);
    box.length=(uint32_t)size;
    box.exit_code=0;
    box.response=box.request;
    if(!registered) {
        for(unsigned i=0;i<sizeof(box.command);i+=4096)box.command[i]=0;
        registered=1;
        hypercall(0x6d656d6572616873ULL,(uintptr_t)"arena-agent-game",(uintptr_t)&box,sizeof(box));
    }
    /* A distinct code separates the game gate from a late root-agent reply. */
    hypercall(0x656e6f6463657865ULL,0x47415445,0,0);
    box.command[sizeof(box.command)-1]=0;
    return (*env)->NewStringUTF(env,(const char *)box.command);
}

static int bad(JNIEnv *env) {
    if(!(*env)->ExceptionCheck(env))return 0;
    (*env)->ExceptionDescribe(env);
    (*env)->ExceptionClear(env);
    return 1;
}

JNIEXPORT jint JNICALL Agent_OnAttach(JavaVM *vm,char *options,void *reserved) {
    (void)reserved;
    JNIEnv *env=0;
    if(!options || (*vm)->GetEnv(vm,(void **)&env,JNI_VERSION_1_6)!=JNI_OK)return JNI_ERR;
    if((*env)->PushLocalFrame(env,48)<0)return JNI_ERR;
    jint result=JNI_ERR;
    jclass thread=(*env)->FindClass(env,"android/app/ActivityThread");
    if(bad(env))goto done;
    jmethodID current=(*env)->GetStaticMethodID(env,thread,"currentApplication","()Landroid/app/Application;");
    if(bad(env))goto done;
    jobject app=(*env)->CallStaticObjectMethod(env,thread,current);
    if(bad(env) || !app)goto done;
    jclass context=(*env)->FindClass(env,"android/content/Context");
    if(bad(env))goto done;
    jmethodID get_loader=(*env)->GetMethodID(env,context,"getClassLoader","()Ljava/lang/ClassLoader;");
    if(bad(env))goto done;
    jobject parent=(*env)->CallObjectMethod(env,app,get_loader);
    if(bad(env) || !parent)goto done;
    jclass dex=(*env)->FindClass(env,"dalvik/system/DexClassLoader");
    if(bad(env))goto done;
    jmethodID constructor=(*env)->GetMethodID(env,dex,"<init>","(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/ClassLoader;)V");
    if(bad(env))goto done;
    jstring jar=(*env)->NewStringUTF(env,options);
    jstring cache=(*env)->NewStringUTF(env,"/data/data/com.pandadastudio.ninjamustdie3/code_cache");
    jobject loader=(*env)->NewObject(env,dex,constructor,jar,cache,(jobject)0,parent);
    if(bad(env) || !loader)goto done;
    jclass class_loader=(*env)->FindClass(env,"java/lang/ClassLoader");
    if(bad(env))goto done;
    jmethodID load=(*env)->GetMethodID(env,class_loader,"loadClass","(Ljava/lang/String;)Ljava/lang/Class;");
    if(bad(env))goto done;
    jstring name=(*env)->NewStringUTF(env,"dev.mr3a.checkpoint.Gate");
    jclass gate=(jclass)(*env)->CallObjectMethod(env,loader,load,name);
    if(bad(env) || !gate)goto done;
    JNINativeMethod native={"exchange","(Ljava/lang/String;)Ljava/lang/String;",(void *)exchange};
    if((*env)->RegisterNatives(env,gate,&native,1)!=JNI_OK || bad(env))goto done;
    jmethodID create=(*env)->GetMethodID(env,gate,"<init>","()V");
    if(bad(env))goto done;
    jobject instance=(*env)->NewObject(env,gate,create);
    if(bad(env) || !instance)goto done;
    jclass system=(*env)->FindClass(env,"java/lang/System");
    if(bad(env))goto done;
    jmethodID get_props=(*env)->GetStaticMethodID(env,system,"getProperties","()Ljava/util/Properties;");
    if(bad(env))goto done;
    jobject props=(*env)->CallStaticObjectMethod(env,system,get_props);
    if(bad(env) || !props)goto done;
    jclass map=(*env)->FindClass(env,"java/util/Map");
    if(bad(env))goto done;
    jmethodID put=(*env)->GetMethodID(env,map,"put","(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;");
    if(bad(env))goto done;
    jstring key=(*env)->NewStringUTF(env,"mr3a.checkpoint.gate");
    (*env)->CallObjectMethod(env,props,put,key,instance);
    if(bad(env))goto done;
    result=JNI_OK;
done:
    (*env)->PopLocalFrame(env,0);
    return result;
}
