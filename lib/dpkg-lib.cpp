
#include <apt-pkg/debversion.h>

extern "C" {

#include "dpkg.h"

int cmpversions(char *left, int op, char *right) {
	int i = debVS.CmpVersion(left, right);

	switch(op) {
		case dr_LT:    return i <  0;
		case dr_LTEQ:  return i <= 0;
		case dr_EQ:    return i == 0;
		case dr_GTEQ:  return i >= 0;
		case dr_GT:    return i >  0;
	}
	return 0;
}

}

#ifdef TESTBIN
int main(int argc, char **argv) {
	if (argc != 3) { printf("Usage: %s <ver> <ver>\n", argv[0]); exit(1); }

	printf("%d\n", versioncmp(argv[1], argv[2]));
	return 0;
}
#endif
