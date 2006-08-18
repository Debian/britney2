#include <stdio.h>
#include <stdlib.h>
#include "templates.h"

typedef unsigned long ul;

#define SIZE          (sizeof(ul) * 8)
#define ROUND_DOWN(x) ((x) & ~(SIZE-1))
#define ROUND_UP(x)   ROUND_DOWN((x) + (SIZE-1))
#define NEXT_UP(x)    ROUND_DOWN((x) + SIZE)
#define NEXT_DOWN(x)  ROUND_DOWN((x) - 1)

#define SETBIT(s,p) \
		assert( (bits[(s)/SIZE] & (p)) == (setp ? 0 : (p)) ); \
		if (setp) bits[(s)/SIZE] |= (p); \
		else      bits[(s)/SIZE] &= ~(p)

#define GETBIT(s) (bits[ROUND_DOWN(s)/SIZE] & (1ul << (NEXT_UP(s) - s - 1)))

size_t count_free_bits_back(ul *bits, size_t s) {
	size_t cnt = 0;
	ul w = ROUND_DOWN(s) / SIZE;
	size_t add = s % SIZE;
	ul off = (~0ul) << (SIZE - add);
	ul H, d;

	while ((bits[w] & off) == 0) {
		cnt += add;
		add = SIZE;
		off = ~0ul;
		if (w == 0)
			return cnt;
		w--;
	}

	H = add;
	add = 0;
	while ((d = (H - add) / 2) > 0) {
		ul offM = (off >> d) & off;
		if (bits[w] & offM) {
			off = offM;
			H = H - d;
		} else {
			add = H - d;
		}
	}
	cnt += add;
	return cnt;
}

size_t count_free_bits_after(ul *bits, size_t s, size_t end) {
	size_t cnt = 0;
	ul w = ROUND_DOWN(s) / SIZE;
	size_t add = SIZE - s % SIZE;
	ul off = (~0ul) >> (SIZE - add);
	ul H, d;

	end /= SIZE;

	while ((bits[w] & off) == 0) {
		cnt += add;
		add = SIZE;
		off = ~0ul;
		w++;
		if (w == end)
			return cnt;
	}

	H = add;
	add = 0;
	while ((d = (H - add) / 2) > 0) {
		ul offM = off << d;
		if (bits[w] & offM) {
			off = offM;
			H = H - d;
		} else {
			add = H - d;
		}
	}
	cnt += add;
	return cnt;
}

void find_long_freebits(ul *bits, size_t s, ul *start, size_t *size) {
        ul clen = 0;
        ul bstart = 0, blen = 0;
        ul i, k;

        for (i = 0; i < s; i++) {
                if (bits[i] == 0) {
			clen++;
		} else {
			if (clen > blen) {
				bstart = i - clen;
				blen = clen;
			}
			clen = 0;
		}
	}

	if (blen == 0) return;

	bstart *= SIZE; blen *= SIZE;
	k = count_free_bits_back(bits, bstart);
	bstart -= k; blen += k;

	blen += count_free_bits_after(bits, bstart + blen, s*SIZE);

	*start = bstart; *size = blen;
}

void mark_bits(ul *bits, ul s, size_t size, int setp) {
	ul e = s+size;

	ul rds = ROUND_DOWN(s);
	ul nus = rds + SIZE;
	ul rue = ROUND_UP(e);

	ul patl = (~0UL) >> (s % SIZE);
	ul patr = (~0UL) << (rue - e);

	assert(size > 0);

	/* bits[s1..e1] get touched, but bits[s1], bits[e1] only partially
	 *
	 * if s1 == e1, then bits[s1] get touched from [s%SIZE, e%SIZE)
	 * else
	 *     bits[s1] gets touched from [s%SIZE, SIZE)
	 *     bits[s2..e1) get reset completely
	 *     bits[e1] gets touched from [0, e%SIZE)
	 */

	if (nus >= e) {
		/* ROUND_DOWN(s) <= s < e <= NEXT_UP(s) */
		SETBIT(rds, patl & patr);
	} else {
		/* ROUND_DOWN(s) <= s < NEXT_UP(s) <= NEXT_DOWN(e) < e */
		ul rde = ROUND_DOWN(e);

		SETBIT(rds, patl);
		SETBIT(rde, patr);
		while (nus < rde) {	
			SETBIT(nus, ~0UL);
			nus += SIZE;
		}
	}
}

void print_bits(ul *bits, ul s) {
	ul i;
	putchar(' ');
	for (i = 0; i < s * SIZE; i++) {
		putchar( GETBIT(i) ? '1' : '0' );
	}
}
	
#ifdef TESTBIN

#define X 2
int main(void) {
	ul memory[X];
	ul l, r;
	ul k = 5;

	memset(memory, 0, sizeof(memory));
	for (l = 0; l < X*SIZE; l += k) {
		for (r = 1; l+(r*r) < X*SIZE; r++) {

			printf("%lu %lu (%lu %lu", l, r*r,
			    (unsigned long) count_free_bits_back(memory, X*SIZE), (unsigned long) X*SIZE);
			mark_bits(memory, l, r*r, 1);
			printf("; %lu %lu %lu; %lu %lu %lu;): ", 
			    (unsigned long) count_free_bits_back(memory, X*SIZE) + l + r*r, 
			    (unsigned long) count_free_bits_after(memory, l + r*r, X*SIZE) + l + r*r,
			    (unsigned long) X*SIZE,
			    (unsigned long) count_free_bits_back(memory, l), 
			    (unsigned long) count_free_bits_after(memory, 0, X*SIZE), 
			    l);
			print_bits(memory, X);
			printf("\n");

			mark_bits(memory, l, r*r, 0);
		}
	}

	return 0;
}
#endif
