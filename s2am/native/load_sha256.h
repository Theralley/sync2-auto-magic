#ifndef S2AM_LOAD_SHA256_H
#define S2AM_LOAD_SHA256_H
/* Reused verbatim from the existing tested s2amdrive SHA-256 core. */
typedef struct {
    DWORD state[8], bytes_low, bytes_high, fill;
    BYTE block[64];
} Sha256;

static const DWORD sha_k[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
};

#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static void sha256_block(Sha256 *sha, const BYTE *p)
{
    DWORD w[64], v[8], t1, t2;
    int i;
    for (i = 0; i < 16; i++)
        w[i] = (DWORD)p[4 * i] << 24 | (DWORD)p[4 * i + 1] << 16 | (DWORD)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (i = 16; i < 64; i++)
        w[i] = w[i - 16] + (ROR(w[i - 15], 7) ^ ROR(w[i - 15], 18) ^ (w[i - 15] >> 3)) + w[i - 7] +
               (ROR(w[i - 2], 17) ^ ROR(w[i - 2], 19) ^ (w[i - 2] >> 10));
    for (i = 0; i < 8; i++)
        v[i] = sha->state[i];
    for (i = 0; i < 64; i++) {
        t1 = v[7] + (ROR(v[4], 6) ^ ROR(v[4], 11) ^ ROR(v[4], 25)) + ((v[4] & v[5]) ^ (~v[4] & v[6])) +
             sha_k[i] + w[i];
        t2 = (ROR(v[0], 2) ^ ROR(v[0], 13) ^ ROR(v[0], 22)) + ((v[0] & v[1]) ^ (v[0] & v[2]) ^ (v[1] & v[2]));
        v[7] = v[6];
        v[6] = v[5];
        v[5] = v[4];
        v[4] = v[3] + t1;
        v[3] = v[2];
        v[2] = v[1];
        v[1] = v[0];
        v[0] = t1 + t2;
    }
    for (i = 0; i < 8; i++)
        sha->state[i] += v[i];
}

static void sha256_init(Sha256 *sha)
{
    static const DWORD start[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                   0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    memcpy(sha->state, start, sizeof(start));
    sha->bytes_low = sha->bytes_high = sha->fill = 0;
}

static void sha256_update(Sha256 *sha, const BYTE *data, DWORD length)
{
    DWORD before = sha->bytes_low;
    sha->bytes_low += length;
    if (sha->bytes_low < before)
        sha->bytes_high++;
    if (sha->fill) {
        while (length && sha->fill < 64) {
            sha->block[sha->fill++] = *data++;
            length--;
        }
        if (sha->fill < 64)
            return;
        sha256_block(sha, sha->block);
        sha->fill = 0;
    }
    for (; length >= 64; data += 64, length -= 64)
        sha256_block(sha, data);
    while (length--)
        sha->block[sha->fill++] = *data++;
}

static void sha256_final(Sha256 *sha, BYTE digest[32])
{
    DWORD high = sha->bytes_high << 3 | sha->bytes_low >> 29, low = sha->bytes_low << 3;
    int i;
    sha->block[sha->fill++] = 0x80;
    if (sha->fill > 56) {
        while (sha->fill < 64)
            sha->block[sha->fill++] = 0;
        sha256_block(sha, sha->block);
        sha->fill = 0;
    }
    while (sha->fill < 56)
        sha->block[sha->fill++] = 0;
    for (i = 0; i < 4; i++) {
        sha->block[56 + i] = (BYTE)(high >> (24 - 8 * i));
        sha->block[60 + i] = (BYTE)(low >> (24 - 8 * i));
    }
    sha256_block(sha, sha->block);
    for (i = 0; i < 32; i++)
        digest[i] = (BYTE)(sha->state[i / 4] >> (24 - 8 * (i % 4)));
}


#endif
