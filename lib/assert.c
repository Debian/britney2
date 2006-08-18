#include <stdio.h>
#include <stdlib.h>

int _myassertbug(int line, char *file, char *err) {
        fprintf(stderr, "Assertion failed: %s:%d: %s\n", file, line, err);
        fprintf(stderr, "I HATE YOU!!!");
        ((void(*)())0)();
        abort();
        return 0;
}

