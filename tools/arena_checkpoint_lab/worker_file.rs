//! Named-instance KVM worker. The control socket belongs to the host, never the guest.
use std::collections::HashMap;
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::sync::Arc;
use std::sync::atomic::{AtomicPtr,Ordering,fence};
use std::time::{Duration, Instant};
use nyx_lite::{ExitReason, NyxVM};
use nyx_lite::mem::NyxMemExtension;
use nyx_lite::snapshot::{MemorySnapshot, NyxSnapshot};
use serde_json::{json, Value};
use vmm::devices::virtio::block::persist::BlockState;
use vmm::devices::virtio::block::virtio::io::cow_io::CowCache;

#[derive(Default)]
struct DiskLayers(Vec<Arc<CowCache>>);

impl DiskLayers {
    fn retain_snapshot(&mut self, point:&NyxSnapshot) {
        // Upstream disk ancestors are Weak, unlike RAM snapshot parents.
        // Keep their small COW layers independently when a RAM tree is freed.
        // Keeping all IDs also avoids upstream len-based ID reuse after GC.
        for disk in &point.state.device_states.block_devices {
            if let BlockState::Virtio(state)=&disk.device_state {
                self.0.push(state.cow_state.clone());
            }
        }
    }
}

struct Agent { address: u64, cr3: u64, size: usize }
static RUN_PAGE:AtomicPtr<kvm_bindings::kvm_run>=AtomicPtr::new(std::ptr::null_mut());

extern "C" fn kick(_:libc::c_int,_:*mut libc::siginfo_t,_:*mut libc::c_void) {
    let page=RUN_PAGE.load(Ordering::Acquire);
    if !page.is_null() { unsafe { std::ptr::write_volatile(std::ptr::addr_of_mut!((*page).immediate_exit),1); } }
    fence(Ordering::Release);
}

fn install_kick(vm:&mut NyxVM) {
    // Nyx runs this vCPU on the main thread, outside Firecracker's private TLS.
    // Bind the signal to the stable KVM_RUN mapping, avoiding a lost pre-run kick.
    let page=vm.vcpu.kvm_vcpu.fd.get_kvm_run() as *mut kvm_bindings::kvm_run;
    RUN_PAGE.store(page,Ordering::Release);
    unsafe {
        let mut action:libc::sigaction=std::mem::zeroed();
        action.sa_sigaction=kick as *const () as usize;
        action.sa_flags=libc::SA_SIGINFO;
        libc::sigemptyset(&mut action.sa_mask);
        assert_eq!(libc::sigaction(utils::signal::sigrtmin()+vmm::vstate::vcpu::VCPU_RTSIG_OFFSET,
                                  &action,std::ptr::null_mut()),0);
    }
}
struct PausedTime { tsc:u64, clock:kvm_bindings::kvm_clock_data }

fn paused_time(vm:&NyxVM)->PausedTime {
    let tsc=vm.vcpu.kvm_vcpu.get_msrs(&vec![0x10]).unwrap()[&0x10];
    let mut clock=vm.vmm.lock().unwrap().vm.fd().get_clock().unwrap();
    clock.flags=0;
    PausedTime{tsc,clock}
}

fn resume_time(vm:&mut NyxVM,time:&PausedTime) {
    vm.vmm.lock().unwrap().vm.fd().set_clock(&time.clock).unwrap();
    let entries=[kvm_bindings::kvm_msr_entry{index:0x10,data:time.tsc.wrapping_add(0xdeadc0debeef),..Default::default()},
                 kvm_bindings::kvm_msr_entry{index:0x10,data:time.tsc,..Default::default()}];
    let values=kvm_bindings::Msrs::from_entries(&entries).unwrap();
    assert_eq!(vm.vcpu.kvm_vcpu.fd.set_msrs(&values).unwrap(),2);
}

fn read(vm: &NyxVM, agent: &Agent, offset: u64, size: usize) -> Result<Vec<u8>, String> {
    if offset as usize + size > agent.size { return Err("agent buffer bounds".into()); }
    let mut bytes = vec![0; size];
    vm.vmm.lock().unwrap().read_virtual_bytes(agent.cr3, agent.address + offset, &mut bytes)
        .map_err(|error| format!("guest memory: {error:?}"))?;
    Ok(bytes)
}

fn main() {
    // An interrupted Python lease owner must not leave an unowned running VM.
    let parent = unsafe { libc::getppid() };
    assert!(parent > 1, "worker requires its named runtime owner");
    assert_eq!(unsafe { libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM) },0);
    if unsafe { libc::getppid() } != parent { return; }
    let args: Vec<String> = env::args().collect();
    let config = fs::read_to_string(&args[1]).expect("guest config");
    let parsed: Value = serde_json::from_str(&config).unwrap();
    assert_eq!(parsed["network-interfaces"], json!([]), "search guest has no network");
    assert_eq!(parsed["machine-config"]["vcpu_count"], json!(1), "search guest uses one vCPU");
    let checkpoint_enabled=parsed["drives"].as_array().unwrap().iter().all(|v|v["io_engine"]=="Cow");
    let socket = &args[2];
    let file_ram=env::var_os("MR3A_CHECKPOINT_FILE_RAM").as_deref()==Some(std::ffi::OsStr::new("1"));
    if file_ram {
        let directory=std::path::Path::new(socket).parent().unwrap().join("ram-history");
        fs::create_dir_all(&directory).unwrap();
        fs::set_permissions(&directory,fs::Permissions::from_mode(0o700)).unwrap();
        env::set_var("NYX_RAM_BACKING_DIR",directory);
    } else {env::remove_var("NYX_RAM_BACKING_DIR");}
    assert!(!std::path::Path::new(socket).exists(), "refuse an existing control socket");
    let listener = UnixListener::bind(socket).expect("private instance control socket");
    fs::set_permissions(socket, fs::Permissions::from_mode(0o600)).unwrap();
    let mut vm = NyxVM::new("arena-search".into(), &config);
    install_kick(&mut vm);
    let mut agent: Option<Agent> = None;
    let mut points: HashMap<u64, Arc<NyxSnapshot>> = HashMap::new();
    let mut disk_layers=DiskLayers::default();
    let mut sequence = 0u64;
    let mut request_id = 0u32;
    let mut parked:Option<PausedTime>=None;
    for stream in listener.incoming() {
        let mut stream = stream.unwrap();
        let mut reader = BufReader::new(stream.try_clone().unwrap());
        let mut line = String::new();
        if reader.read_line(&mut line).is_err() || line.len() > 1_000_000 { continue; }
        let start = Instant::now();
        let result = (|| -> Result<Value, String> {
            let request: Value = serde_json::from_str(&line).map_err(|e| e.to_string())?;
            let op = request["op"].as_str().ok_or("missing operation")?;
            match op {
                "status" => Ok(json!({"snapshots":points.len(),"agent_ready":agent.is_some(),"checkpoint_enabled":checkpoint_enabled,"can_rebase":true,"retained_disk_layers":disk_layers.0.len(),"file_ram":file_ram,"file_ram_restore":"batched-latest-page-v1"})),
                "run" => {
                    let ms = request["ms"].as_u64().unwrap_or(100);
                    if ms == 0 || ms > 5000 { return Err("run duration must be 1..5000ms".into()); }
                    let until = Instant::now() + Duration::from_millis(ms);
                    let mut reason = String::new();
                    let mut output = None;
                    if let Some(time)=&parked { resume_time(&mut vm,time); }
                    while Instant::now() < until {
                        let exit = vm.run(Duration::from_millis(20));
                        parked=Some(paused_time(&vm));
                        match exit {
                            ExitReason::SharedMem(name, address, size) => {
                                if name.starts_with("arena-agent") {
                                    agent = Some(Agent{address, size, cr3:vm.sregs().cr3});
                                    reason = "agent_registered".into(); break;
                                }
                            },
                            ExitReason::ExecDone(code) => {
                                reason = "command_done".into();
                                if let Some(a) = &agent {
                                    let header = read(&vm,a,0,16)?;
                                    let length = u32::from_le_bytes(header[12..16].try_into().unwrap()) as usize;
                                    let bytes = read(&vm,a,4112,length)?;
                                    output = Some(json!({"id":u32::from_le_bytes(header[4..8].try_into().unwrap()),
                                        "exit_code":i32::from_le_bytes(header[8..12].try_into().unwrap()),
                                        "text":String::from_utf8_lossy(&bytes),"code":code}));
                                }
                                break;
                            },
                            ExitReason::Hypercall(0x747365746c696166,p,_,_,_) =>
                                return Err(format!("guest boot: {}",String::from_utf8_lossy(&vm.read_cstr_current(p)))),
                            ExitReason::Shutdown => return Err("guest shut down".into()),
                            ExitReason::DebugPrint(message) => eprintln!("guest: {message}"),
                            other => reason = format!("{other:?}"),
                        }
                    }
                    Ok(json!({"reason":reason,"output":output,"agent_ready":agent.is_some()}))
                },
                "command" | "upload" => {
                    let a = agent.as_ref().ok_or("guest agent not registered")?;
                    let mut owned=String::new();
                    if op=="upload" {
                        let path=request["path"].as_str().ok_or("missing guest path")?;
                        if !path.starts_with("/data/local/tmp/arena-search/") || path.contains("..") || path.chars().any(char::is_whitespace) {
                            return Err("upload is restricted to the private guest staging directory".into());
                        }
                        let offset=request["offset"].as_u64().ok_or("missing upload offset")?;
                        let hex=request["hex"].as_str().ok_or("missing upload bytes")?;
                        if !hex.is_ascii() || hex.len()%2!=0 || hex.len()>524288 { return Err("upload chunk limit".into()); }
                        let bytes:Result<Vec<u8>,_>=(0..hex.len()).step_by(2).map(|i|u8::from_str_radix(&hex[i..i+2],16)).collect();
                        let bytes=bytes.map_err(|e|e.to_string())?;
                        let vmm=vm.vmm.lock().unwrap();
                        vmm.write_virtual_bytes(a.cr3,a.address+4112,&bytes).map_err(|e|format!("{e:?}"))?;
                        vmm.write_virtual_u64(a.cr3,a.address+8,(bytes.len() as u64)<<32).map_err(|e|format!("{e:?}"))?;
                        owned=format!("@write {path} {offset}");
                    }
                    let text = if op=="upload" {owned.as_str()} else {request["text"].as_str().ok_or("missing command")?};
                    if text.len() >= 4096 || text.as_bytes().contains(&0) { return Err("command limit".into()); }
                    request_id = request_id.checked_add(1).ok_or("request counter exhausted")?;
                    let mut bytes = vec![0u8;4096];
                    bytes[..text.len()].copy_from_slice(text.as_bytes());
                    let vmm = vm.vmm.lock().unwrap();
                    vmm.write_virtual_bytes(a.cr3,a.address+16,&bytes).map_err(|e|format!("{e:?}"))?;
                    vmm.write_virtual_u64(a.cr3,a.address,request_id as u64).map_err(|e|format!("{e:?}"))?;
                    Ok(json!({"id":request_id}))
                },
                "snapshot" => {
                    if !checkpoint_enabled {return Err("snapshot disabled while provisioning a direct-write private disk".into());}
                    if let Some(time)=&parked { resume_time(&mut vm,time); }
                    sequence+=1;
                    let point=vm.take_snapshot();
                    disk_layers.retain_snapshot(&point);
                    parked=Some(PausedTime{tsc:point.tsc,clock:point.rewind_clock});
                    let bytes=match &point.memory {MemorySnapshot::Base(v)=>v.len(),MemorySnapshot::Incremental(v)=>v.len()*4096,MemorySnapshot::Mapped(v)=>v.len()};
                    if file_ram && !matches!(&point.memory,MemorySnapshot::Mapped(_)) {
                        return Err("RAM backing failed; no checkpoint ID was published".into());
                    }
                    points.insert(sequence,point);
                    Ok(json!({"id":sequence,"bytes":bytes}))
                },
                "restore" => {
                    if !checkpoint_enabled {return Err("restore disabled while provisioning".into());}
                    let id=request["id"].as_u64().ok_or("missing snapshot id")?;
                    let point=points.get(&id).ok_or("unknown snapshot")?;
                    vm.apply_snapshot(point);
                    parked=Some(PausedTime{tsc:point.tsc,clock:point.rewind_clock});
                    Ok(json!({"id":id}))
                },
                "rebase" => {
                    if !checkpoint_enabled {return Err("rebase disabled while provisioning".into());}
                    if let Some(time)=&parked {resume_time(&mut vm,time);}
                    // Build a new complete RAM root at the current stopped
                    // state. Retain the old tree until capture succeeds. COW
                    // disk caches belong to the device, not the RAM parents.
                    let previous=vm.active_snapshot.take();
                    let point=vm.take_snapshot();
                    disk_layers.retain_snapshot(&point);
                    assert!(point.parent.is_none());
                    let bytes=match &point.memory {
                        MemorySnapshot::Base(v)=>v.len(),
                        MemorySnapshot::Mapped(v) if v.base=>v.len(),
                        _=>panic!("rebase did not produce a complete RAM root"),
                    };
                    let replaced=points.len();
                    points.clear();
                    drop(previous);
                    sequence+=1;
                    parked=Some(PausedTime{tsc:point.tsc,clock:point.rewind_clock});
                    points.insert(sequence,point);
                    Ok(json!({"id":sequence,"bytes":bytes,"replaced":replaced,"file_backed":file_ram && matches!(&points[&sequence].memory,MemorySnapshot::Mapped(_))}))
                },
                "drop" => {let id=request["id"].as_u64().ok_or("missing snapshot id")?;points.remove(&id);Ok(json!({"id":id}))},
                "shutdown" => Ok(json!({"shutdown":true})),
                _ => Err("unknown operation".into()),
            }
        })();
        let shutdown = result.as_ref().ok().and_then(|v|v["shutdown"].as_bool()).unwrap_or(false);
        let response = match result {Ok(value)=>json!({"ok":true,"result":value,"ms":start.elapsed().as_secs_f64()*1000.0}),
            Err(error)=>json!({"ok":false,"error":error})};
        let _=writeln!(stream,"{response}");
        if shutdown {break;}
    }
    let _=fs::remove_file(socket);
    RUN_PAGE.store(std::ptr::null_mut(),Ordering::Release);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::OpenOptions;
    use vm_memory::VolatileSlice;
    use vmm::devices::virtio::block::virtio::io::cow_io::CowCacheTree;

    #[test]
    fn disk_parents_survive_when_old_ram_snapshot_owners_are_released() {
        let path=std::env::temp_dir().join(format!("mr3a-cow-rebase-{}",std::process::id()));
        let mut file=OpenOptions::new().create_new(true).read(true).write(true).open(&path).unwrap();
        file.set_len(1024).unwrap();
        let mut tree=CowCacheTree::new();
        let mut source=[0x31u8;512];
        let input=unsafe{VolatileSlice::new(source.as_mut_ptr(),512)};
        tree.write(0,&input);
        let root=tree.snapshot();
        source.fill(0x42);
        tree.write(512,&input);
        let child=tree.snapshot();
        let mut disk=DiskLayers::default();
        disk.0.push(root.clone());
        disk.0.push(child.clone());
        let child_id=child.id;
        drop(root);
        drop(child);
        // This actual block read panics in the failed RAM-only rebase.
        let mut bytes=[0u8;1024];
        let mut output=unsafe{VolatileSlice::new(bytes.as_mut_ptr(),bytes.len())};
        tree.read(&mut file,0,&mut output);
        assert_eq!(&bytes[..512],&[0x31;512]);
        assert_eq!(&bytes[512..],&[0x42;512]);
        for _ in 0..8 {
            tree.reset_to(child_id);
            source.fill(0x53);
            tree.write(0,&input);
            let next=tree.snapshot();
            disk.0.push(next);
            tree.read(&mut file,0,&mut output);
            assert_eq!(&bytes[..512],&[0x53;512]);
            assert_eq!(&bytes[512..],&[0x42;512]);
        }
        drop(file);
        fs::remove_file(path).unwrap();
    }
}
