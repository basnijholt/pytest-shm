# pytest-shm

Put pytest's temporary files on the `/dev/shm` tmpfs so fsync-heavy suites stop waiting on the disk.
