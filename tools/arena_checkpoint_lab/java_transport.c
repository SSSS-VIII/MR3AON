/* One-shot Java -> original UnitySendMessage, using Android's userdebug
 * attach-agent API. No JVMTI hooks, patched instructions, or worker threads.
 * JNI calls run on the Java thread supplied by Android, then return.
 */
#include <jni.h>
#include <sys/syscall.h>
#include <fcntl.h>

static long system_call(long number,long a,long b,long c,long d) {
    long result;
    register long d10 __asm__("r10")=d;
    __asm__ volatile("syscall":"=a"(result):"a"(number),"D"(a),"S"(b),"d"(c),"r"(d10):"rcx","r11","memory");
    return result;
}

static unsigned length(const char *text) {unsigned n=0;while(text[n])n++;return n;}
static void status(const char *text) {
    const char *path="/sdcard/Android/data/com.pandadastudio.ninjamustdie3/files/arena-control/native-agent-status.txt";
    long fd=system_call(SYS_openat,AT_FDCWD,(long)path,O_WRONLY|O_CREAT|O_TRUNC,0600);
    if(fd>=0) {system_call(SYS_write,fd,(long)text,length(text),0);system_call(SYS_close,fd,0,0,0);}
}

static int failed(JNIEnv *env,const char *step) {
    if(!(*env)->ExceptionCheck(env))return 0;
    (*env)->ExceptionDescribe(env);
    (*env)->ExceptionClear(env);
    status(step);
    return 1;
}

static jclass load_class(JNIEnv *env,jobject loader,const char *name) {
    jclass type=(*env)->FindClass(env,"java/lang/ClassLoader");
    if(failed(env,"ClassLoader unavailable"))return 0;
    jmethodID method=(*env)->GetMethodID(env,type,"loadClass","(Ljava/lang/String;)Ljava/lang/Class;");
    if(failed(env,"ClassLoader method unavailable"))return 0;
    jstring text=(*env)->NewStringUTF(env,name);
    jobject result=(*env)->CallObjectMethod(env,loader,method,text);
    (*env)->DeleteLocalRef(env,text);
    return (jclass)result;
}

static jobject field_value(JNIEnv *env,jclass type,jobject object,const char *name) {
    jclass clazz=(*env)->FindClass(env,"java/lang/Class");
    if(failed(env,"Class unavailable"))return 0;
    jmethodID declared=(*env)->GetMethodID(env,clazz,"getDeclaredField","(Ljava/lang/String;)Ljava/lang/reflect/Field;");
    if(failed(env,"Class field method unavailable"))return 0;
    jstring text=(*env)->NewStringUTF(env,name);
    jobject field=(*env)->CallObjectMethod(env,type,declared,text);
    if((*env)->ExceptionCheck(env))return 0;
    jclass reflection=(*env)->FindClass(env,"java/lang/reflect/Field");
    if(failed(env,"Field unavailable"))return 0;
    jmethodID accessible=(*env)->GetMethodID(env,reflection,"setAccessible","(Z)V");
    if(failed(env,"Field access method unavailable"))return 0;
    jmethodID get=(*env)->GetMethodID(env,reflection,"get","(Ljava/lang/Object;)Ljava/lang/Object;");
    if(failed(env,"Field value method unavailable"))return 0;
    (*env)->CallVoidMethod(env,field,accessible,JNI_TRUE);
    if(failed(env,"Field access denied"))return 0;
    return (*env)->CallObjectMethod(env,field,get,object);
}

static void quiet_statistics(JNIEnv *env,jobject loader) {
    /* Same SDK-owned retry loopers as arena_bootstrap; never quit main. */
    jclass type=load_class(env,loader,"com.reyun.tracking.sdk.ReYunWorkHandler");
    if(failed(env,"statistics class unavailable"))return;
    jobject handlers=field_value(env,type,0,"sHandlers");
    if(failed(env,"statistics handlers unavailable") || !handlers)return;
    jclass map=(*env)->FindClass(env,"java/util/Map");
    if(failed(env,"Map unavailable"))return;
    jmethodID values=(*env)->GetMethodID(env,map,"values","()Ljava/util/Collection;");
    if(failed(env,"Map values unavailable"))return;
    jobject collection=(*env)->CallObjectMethod(env,handlers,values);
    if(failed(env,"Map values failed"))return;
    jclass coll=(*env)->FindClass(env,"java/util/Collection");
    if(failed(env,"Collection unavailable"))return;
    jmethodID iterator=(*env)->GetMethodID(env,coll,"iterator","()Ljava/util/Iterator;");
    if(failed(env,"Collection iterator unavailable"))return;
    jobject it=(*env)->CallObjectMethod(env,collection,iterator);
    if(failed(env,"Collection iterator failed"))return;
    jclass iter=(*env)->FindClass(env,"java/util/Iterator");
    if(failed(env,"Iterator unavailable"))return;
    jmethodID has_next=(*env)->GetMethodID(env,iter,"hasNext","()Z");
    if(failed(env,"Iterator hasNext unavailable"))return;
    jmethodID next=(*env)->GetMethodID(env,iter,"next","()Ljava/lang/Object;");
    if(failed(env,"Iterator next unavailable"))return;
    jclass looper=(*env)->FindClass(env,"android/os/Looper");
    if(failed(env,"Looper unavailable"))return;
    jmethodID get_main=(*env)->GetStaticMethodID(env,looper,"getMainLooper","()Landroid/os/Looper;");
    if(failed(env,"Main Looper method unavailable"))return;
    jobject main=(*env)->CallStaticObjectMethod(env,looper,get_main);
    if(failed(env,"Main Looper lookup failed"))return;
    jmethodID quit=(*env)->GetMethodID(env,looper,"quitSafely","()V");
    if(failed(env,"Looper quit method unavailable"))return;
    jclass handler=(*env)->FindClass(env,"android/os/Handler");
    if(failed(env,"Handler unavailable"))return;
    jmethodID get_loop=(*env)->GetMethodID(env,handler,"getLooper","()Landroid/os/Looper;");
    if(failed(env,"Handler Looper method unavailable"))return;
    jmethodID remove=(*env)->GetMethodID(env,handler,"removeCallbacksAndMessages","(Ljava/lang/Object;)V");
    if(failed(env,"Handler remove method unavailable"))return;
    jmethodID clear=(*env)->GetMethodID(env,type,"clearTasks","()V");
    if(failed(env,"statistics method lookup failed"))return;
    for(;;) {
        jboolean more=(*env)->CallBooleanMethod(env,it,has_next);
        if(failed(env,"Statistics iteration failed") || !more)return;
        jobject instance=(*env)->CallObjectMethod(env,it,next);
        if(failed(env,"Statistics instance failed"))return;
        jobject work=field_value(env,type,instance,"mWorkHandler");
        if(failed(env,"statistics handler lookup failed"))return;
        if(!work)continue;
        jobject loop=(*env)->CallObjectMethod(env,work,get_loop);
        if(failed(env,"Statistics Looper lookup failed"))return;
        if(!(*env)->IsSameObject(env,loop,main)) {
            (*env)->CallVoidMethod(env,instance,clear);
            if(failed(env,"Statistics clear failed"))return;
            (*env)->CallVoidMethod(env,work,remove,(jobject)0);
            if(failed(env,"Statistics remove failed"))return;
            (*env)->CallVoidMethod(env,loop,quit);
        }
        if(failed(env,"statistics shutdown failed"))return;
    }
}

JNIEXPORT jint JNICALL Agent_OnAttach(JavaVM *vm,char *options,void *reserved) {
    (void)reserved;
    JNIEnv *env=0;
    if((*vm)->GetEnv(vm,(void **)&env,JNI_VERSION_1_6)!=JNI_OK || !options)return JNI_ERR;
    char code[8192];
    long fd=system_call(SYS_openat,AT_FDCWD,(long)options,O_RDONLY,0);
    if(fd<0) {status("Lua message file unavailable");return JNI_ERR;}
    long size=system_call(SYS_read,fd,(long)code,sizeof(code)-1,0);
    system_call(SYS_close,fd,0,0,0);
    if(size<=0 || size==(long)sizeof(code)-1) {status("Invalid Lua message size");return JNI_ERR;}
    code[size]=0;
    if((*env)->PushLocalFrame(env,128)<0)return JNI_ERR;
    jclass thread=(*env)->FindClass(env,"android/app/ActivityThread");
    if(failed(env,"ActivityThread unavailable"))goto failure;
    jmethodID current=(*env)->GetStaticMethodID(env,thread,"currentApplication","()Landroid/app/Application;");
    if(failed(env,"currentApplication unavailable"))goto failure;
    jobject application=(*env)->CallStaticObjectMethod(env,thread,current);
    if(failed(env,"Application unavailable") || !application)goto failure;
    jclass context=(*env)->FindClass(env,"android/content/Context");
    if(failed(env,"Context unavailable"))goto failure;
    jmethodID get_loader=(*env)->GetMethodID(env,context,"getClassLoader","()Ljava/lang/ClassLoader;");
    if(failed(env,"Context class loader method unavailable"))goto failure;
    jobject loader=(*env)->CallObjectMethod(env,application,get_loader);
    if(failed(env,"Application class loader unavailable") || !loader)goto failure;
    quiet_statistics(env,loader);
    jclass unity=load_class(env,loader,"com.unity3d.player.UnityPlayer");
    if(failed(env,"UnityPlayer unavailable") || !unity)goto failure;
    jmethodID send=(*env)->GetStaticMethodID(env,unity,"UnitySendMessage","(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V");
    if(failed(env,"UnitySendMessage unavailable") || !send)goto failure;
    jstring target=(*env)->NewStringUTF(env,"GameManager");
    jstring method=(*env)->NewStringUTF(env,"DoString");
    jstring message=(*env)->NewStringUTF(env,code);
    (*env)->CallStaticVoidMethod(env,unity,send,target,method,message);
    if(failed(env,"UnitySendMessage failed"))goto failure;
    status("queued");
    (*env)->PopLocalFrame(env,0);
    return JNI_OK;
failure:
    (*env)->PopLocalFrame(env,0);
    return JNI_ERR;
}
