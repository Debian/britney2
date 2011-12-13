
CC = gcc
CXX = g++
CFLAGS = -Wall -W -O2 -DNDEBUG -DMDEBUG0 -g -p -fPIC
CXXFLAGS += -fPIC

all : britneymodule.so # checklib aptvercmp freelist libajdpkg.a

clean :
	rm -f *.so *.o *~ Makefile.dep gmon.out 
	rm -f freelist aptvercmp checklib libajdpkg.a

checklib : checklib.o dpkg.o dpkg-lib.o memory3.o freelist.o assert.o
	$(CC) $(CFLAGS) -o checklib -lapt-pkg $^ # -lccmalloc -ldl

aptvercmp : dpkg-lib.cpp
	$(CXX) $(CFLAGS) -DTESTBIN -o aptvercmp dpkg-lib.cpp -lapt-pkg

freelist : freelist.c assert.o
	$(CC) $(CFLAGS) -DTESTBIN -o $@ $^

#libajdpkg.a : dpkg.o dpkg-lib.o memory3.o freelist.o assert.o
#	ar rv $@ $^
#	ranlib $@

britneymodule.so : britney-py.o dpkg.o dpkg-lib.o memory3.o freelist.o assert.o
	$(CC) -shared -o britneymodule.so $^ -lapt-pkg

Makefile.dep :
	@gcc -MM *.c *.cpp > Makefile.dep
	@echo Makefile.dep : Makefile *.c *.h >> Makefile.dep

-include Makefile.dep
