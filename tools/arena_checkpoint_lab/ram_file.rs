//! Read-only, reclaimable backing for exact VM memory pages, not game state.
use std::collections::HashMap;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};

static SEQUENCE: AtomicU64 = AtomicU64::new(0);

pub struct FilePages {
    pointer: *mut libc::c_void,
    length: usize,
    pages: HashMap<u64, usize>,
    order: Vec<u64>,
    pub base: bool,
}

// The mapping is immutable after construction. Its lifetime owns munmap.
unsafe impl Send for FilePages {}
unsafe impl Sync for FilePages {}

impl FilePages {
    pub fn create(directory: &Path, base: bool, input: &[(u64, &[u8])]) -> io::Result<Self> {
        fs::create_dir_all(directory)?;
        let name = directory.join(format!("{}-{}.ram", std::process::id(), SEQUENCE.fetch_add(1, Ordering::Relaxed)));
        let mut file = OpenOptions::new().create_new(true).read(true).write(true).mode(0o600).open(&name)?;
        // Backing exists only while this file/mapping is alive, including on
        // failure. It is not a durable checkpoint or a plaintext crash dump.
        fs::remove_file(&name)?;
        let mut pages = HashMap::new();
        let mut order = Vec::new();
        let mut length = 0usize;
        for &(address, bytes) in input {
            if address % 4096 != 0 || bytes.len() % 4096 != 0 {
                return Err(io::Error::new(io::ErrorKind::InvalidInput, "unaligned VM page"));
            }
            for offset in (0..bytes.len()).step_by(4096) {
                let key=address.checked_add(offset as u64).ok_or_else(||io::Error::new(io::ErrorKind::InvalidInput,"page address overflow"))?;
                if pages.insert(key, length+offset).is_some() {
                    return Err(io::Error::new(io::ErrorKind::InvalidInput,"duplicate VM page"));
                }
                order.push(key);
            }
            file.write_all(bytes)?;
            length=length.checked_add(bytes.len()).ok_or_else(||io::Error::new(io::ErrorKind::InvalidInput,"mapping too large"))?;
        }
        let pointer=if length==0 { std::ptr::null_mut() } else {
            let value=unsafe {libc::mmap(std::ptr::null_mut(),length,libc::PROT_READ,libc::MAP_PRIVATE,file.as_raw_fd(),0)};
            if value==libc::MAP_FAILED {return Err(io::Error::last_os_error());}
            value
        };
        // mmap owns a reference to the inode. No open descriptor per snapshot.
        Ok(Self {pointer,length,pages,order,base})
    }

    pub fn len(&self)->usize {self.length}

    pub fn page(&self,address:u64)->Option<&[u8]> {
        self.pages.get(&address).map(|offset|unsafe {
            std::slice::from_raw_parts((self.pointer as *const u8).add(*offset),4096)
        })
    }

    pub fn iter(&self)->impl Iterator<Item=(u64,&[u8])> {
        self.order.iter().enumerate().map(|(index,address)|(*address,unsafe {
            std::slice::from_raw_parts((self.pointer as *const u8).add(index*4096),4096)
        }))
    }
}

impl Drop for FilePages {
    fn drop(&mut self) {
        if self.length>0 {unsafe {libc::munmap(self.pointer,self.length);}}
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exact_sparse_pages_survive_input_release_and_are_not_visible_as_files() {
        let directory=std::env::temp_dir().join(format!("mr3a-pages-{}",std::process::id()));
        let a=(0..8192).map(|i|(i%251)as u8).collect::<Vec<_>>();
        let b=vec![0xa5;4096];
        let saved=FilePages::create(&directory,false,&[(0,&a),(16384,&b)]).unwrap();
        drop(a);drop(b);
        assert_eq!(saved.len(),12288);
        assert_eq!(saved.page(4096).unwrap()[100],((4096+100)%251)as u8);
        assert_eq!(saved.page(16384).unwrap(),vec![0xa5;4096]);
        assert!(saved.page(8192).is_none());
        assert_eq!(saved.iter().count(),3);
        assert_eq!(saved.iter().map(|(address,_)|address).collect::<Vec<_>>(),vec![0,4096,16384]);
        assert_eq!(fs::read_dir(&directory).unwrap().count(),0);
        drop(saved);fs::remove_dir(directory).unwrap();
    }
    #[test]
    fn empty_nodes_and_invalid_ranges_are_explicit() {
        let directory=std::env::temp_dir().join(format!("mr3a-empty-pages-{}",std::process::id()));
        let empty=FilePages::create(&directory,false,&[]).unwrap();
        assert!(empty.page(0).is_none());
        assert_eq!(empty.iter().count(),0);
        assert!(FilePages::create(&directory,false,&[(1,&[0;4096])]).is_err());
        assert!(FilePages::create(&directory,false,&[(0,&[0;4096]),(0,&[1;4096])]).is_err());
        assert_eq!(fs::read_dir(&directory).unwrap().count(),0);
        drop(empty);fs::remove_dir(directory).unwrap();
    }
}
