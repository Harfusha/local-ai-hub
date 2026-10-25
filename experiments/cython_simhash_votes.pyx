from libc.stdint cimport uint64_t


cpdef uint64_t simhash_votes(const uint64_t[::1] hashes):
    cdef Py_ssize_t votes[64]
    cdef Py_ssize_t index
    cdef int bit
    cdef uint64_t value
    cdef uint64_t fingerprint = 0

    for bit in range(64):
        votes[bit] = 0
    for index in range(hashes.shape[0]):
        value = hashes[index]
        for bit in range(64):
            if value & ((<uint64_t>1) << bit):
                votes[bit] += 1
            else:
                votes[bit] -= 1
    for bit in range(64):
        if votes[bit] > 0:
            fingerprint |= (<uint64_t>1) << bit
    return fingerprint
