# greet - build and install.
#
#   make                         build ./greet
#   make check                   run the self-test
#   make install PREFIX=/usr     install to $(DESTDIR)$(PREFIX)/bin/greet
#
# PREFIX and DESTDIR follow the GNU conventions, which is what lets
# distributions (and Nix) install it wherever they need to.

VERSION = 1.0.0

PREFIX ?= /usr/local
BINDIR ?= $(PREFIX)/bin
DESTDIR ?=

CC ?= cc
CFLAGS ?= -O2
CFLAGS += -Wall -Wextra -std=c99

all: greet

greet: greet.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -DGREET_VERSION='"$(VERSION)"' -o $@ greet.c $(LDFLAGS)

check: greet
	test "$$(./greet)" = "Hello from greet $(VERSION)"
	test "$$(./greet --version)" = "greet $(VERSION)"
	./greet --help > /dev/null
	! ./greet --bogus 2> /dev/null

install: greet
	mkdir -p $(DESTDIR)$(BINDIR)
	install -m 755 greet $(DESTDIR)$(BINDIR)/greet

clean:
	rm -f greet

.PHONY: all check install clean
