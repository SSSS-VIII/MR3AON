//! A standalone Nyx-Lite/KVM checkpoint experiment, never a game controller.
//! Restore metrics exclude advancing the guest, but include CPU/device/delta restore.
use std::env;
use std::fs;
use std::sync::Arc;
use std::time::{Duration, Instant};
use nyx_lite::{ExitReason, NyxVM};
use nyx_lite::snapshot::{MemorySnapshot, NyxSnapshot};

fn run(vm: &mut NyxVM) -> ExitReason {
    let end = Instant::now() + Duration::from_secs(20);
    loop {
        assert!(Instant::now() < end, "guest progress timeout");
        match vm.run(Duration::from_secs(2)) {
            ExitReason::DebugPrint(text) => eprintln!("guest: {text}"),
            ExitReason::Timeout => continue,
            ExitReason::Hypercall(0x747365746c696166, address, errno, _, _) => {
                let text = vm.read_cstr_current(address);
                panic!("guest check: {} (errno {errno})", String::from_utf8_lossy(&text));
            },
            reason => return reason,
        }
    }
}

fn observed(vm: &mut NyxVM, address: u64) -> Vec<u64> {
    (1..=8).map(|i| vm.read_current_u64(address + i * 8)).collect()
}

fn advance(vm: &mut NyxVM, address: u64, action: u64, pages: u64) -> Vec<u64> {
    vm.write_current_u64(address, action);
    vm.write_current_u64(address + 80, pages);
    assert!(matches!(run(vm), ExitReason::ExecDone(0)));
    observed(vm, address)
}

fn timed_restore(vm: &mut NyxVM, point: &Arc<NyxSnapshot>, times: &mut Vec<f64>) {
    let start = Instant::now();
    vm.apply_snapshot(point);
    times.push(start.elapsed().as_secs_f64() * 1000.0);
}

fn stats(label: &str, times: &[f64]) {
    let mut sorted = times.to_vec();
    sorted.sort_by(f64::total_cmp);
    let percentile = |p: f64| sorted[((sorted.len() as f64 * p).ceil() as usize).saturating_sub(1)];
    println!("{{\"metric\":\"{label}\",\"count\":{},\"min_ms\":{},\"median_ms\":{},\"p95_ms\":{},\"max_ms\":{}}}",
             sorted.len(), sorted[0], percentile(0.5), percentile(0.95), sorted.last().unwrap());
}

fn delta_bytes(point: &Arc<NyxSnapshot>) -> usize {
    match &point.memory {
        MemorySnapshot::Base(data) => data.len(),
        MemorySnapshot::Mapped(data) => data.len(),
        MemorySnapshot::Incremental(data) => data.len() * 4096,
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let config = fs::read_to_string(args.get(1).expect("config JSON path")).unwrap();
    let rounds: usize = args.get(2).map(|text| text.parse().unwrap()).unwrap_or(120);
    assert!((1..=10_000).contains(&rounds));
    let history: usize = env::var("NYX_BENCH_HISTORY").ok().map(|text|text.parse().unwrap()).unwrap_or(30);
    assert!((30..=1000).contains(&history));
    let mut vm = NyxVM::new("arena-checkpoint-lab".to_string(), &config);
    let address = match run(&mut vm) {
        ExitReason::SharedMem(name, address, size) => {
            assert!(name.starts_with("checkpoint-lab"));
            assert_eq!(size, 4096);
            address
        },
        reason => panic!("guest startup: {reason:?}"),
    };
    assert!(matches!(run(&mut vm), ExitReason::RequestSnapshot));
    let start = Instant::now();
    let base = vm.take_snapshot();
    println!("{{\"metric\":\"base_save\",\"ms\":{},\"bytes\":{}}}",
             start.elapsed().as_secs_f64()*1000.0, delta_bytes(&base));
    let mut saves = Vec::new();
    let mut repeat_restores = Vec::new();
    let mut cross_restores = Vec::new();
    let mut advances = Vec::new();
    let mut points = vec![(base.clone(), observed(&mut vm, address))];
    println!("{{\"metric\":\"guest_capabilities\",\"binder_protocol\":{},\"software_gl\":{}}}",
             vm.read_current_u64(address + 88), vm.read_current_u64(address + 96));
    for index in 0..history {
        let pages = [32, 256, 2048][index % 3];
        let start = Instant::now();
        let values = advance(&mut vm, address, (index % 3) as u64, pages);
        advances.push(start.elapsed().as_secs_f64() * 1000.0);
        let start = Instant::now();
        let point = vm.take_snapshot();
        saves.push(start.elapsed().as_secs_f64() * 1000.0);
        println!("{{\"metric\":\"checkpoint\",\"index\":{},\"dirty_workload_pages\":{},\"saved_bytes\":{},\"ms\":{}}}",
                 index+1, pages, delta_bytes(&point), saves.last().unwrap());
        points.push((point, values));
    }
    // A retained future and a new sibling with unequal depths must also restore.
    vm.apply_snapshot(&points[10].0);
    advance(&mut vm,address,1,32);
    let fork=vm.take_snapshot();
    let fork_expected=observed(&mut vm,address);
    vm.apply_snapshot(&points[history].0);
    vm.apply_snapshot(&fork);
    assert_eq!(observed(&mut vm,address),fork_expected);
    vm.apply_snapshot(&points[history].0);
    assert_eq!(observed(&mut vm,address),points[history].1);
    // Backward jumps, forward jumps to retained futures, and unrelated siblings.
    let mut checks = 0;
    for round in 0..rounds {
        let index = (round * 17 + 7) % points.len();
        let (point, expected) = &points[index];
        timed_restore(&mut vm, point, &mut cross_restores);
        assert_eq!(&observed(&mut vm, address), expected, "checkpoint {index}");
        let action = (round % 3) as u64;
        let first = advance(&mut vm, address, action, 256);
        timed_restore(&mut vm, point, &mut repeat_restores);
        assert_eq!(&observed(&mut vm, address), expected);
        let second = advance(&mut vm, address, action, 256);
        assert_eq!(first, second, "same action from checkpoint {index}");
        checks += 1;
        if round % 10 == 0 {
            let sibling = vm.take_snapshot();
            let left = advance(&mut vm, address, 0, 32);
            timed_restore(&mut vm, &sibling, &mut repeat_restores);
            let right = advance(&mut vm, address, 1, 32);
            assert_ne!(left[1], right[1], "different actions must affect hash");
            timed_restore(&mut vm, &sibling, &mut repeat_restores);
            assert_eq!(advance(&mut vm, address, 0, 32), left);
            checks += 1;
        }
    }
    stats("incremental_save", &saves);
    stats("restore_same_branch_cpu_devices_and_memory", &repeat_restores);
    stats("restore_cross_branch_cpu_devices_and_memory", &cross_restores);
    stats("synthetic_step_with_full_64mib_hash_and_fsync", &advances);
    for index in [0, 15, 30] {
        let point = &points[index].0;
        vm.apply_snapshot(point);
        let before = vm.read_current_u64(address + 14 * 8);
        let timer_before = vm.read_current_u64(address + 15 * 8);
        std::thread::sleep(Duration::from_millis(50));
        vm.apply_snapshot(point);
        vm.write_current_u64(address, 3);
        assert!(matches!(run(&mut vm), ExitReason::ExecDone(0)));
        let after = vm.read_current_u64(address + 16 * 8);
        let timer_after = vm.read_current_u64(address + 17 * 8);
        let expired = vm.read_current_u64(address + 18 * 8);
        let flags = vm.vmm.lock().unwrap().vm.fd().get_clock().unwrap().flags;
        println!("{{\"metric\":\"clock_and_pending_timer\",\"index\":{index},\"clock_error_ns\":{},\"timer_error_ns\":{},\"expired\":{expired},\"kvm_get_clock_flags\":{flags}}}",
                 before.abs_diff(after), timer_before.abs_diff(timer_after));
        assert!(before.abs_diff(after) < 10_000_000, "guest monotonic clock did not rewind");
        assert!(timer_before.abs_diff(timer_after) < 10_000_000, "pending timer deadline did not rewind");
        assert_eq!(expired, 0, "host delay must not expire the saved guest timer");
    }
    println!("{{\"result\":\"pass\",\"repeat_branch_checks\":{checks},\"scope\":\"synthetic Linux guest only; Android and game unvalidated\",\"game_rollback_complete\":false}}");
    // Nyx-Lite's asynchronous event worker has no public join/shutdown API.
    // Normal exit reclaims only this standalone lab's VM; no Android is attached.
}
