/* greet - a tiny program that exists to be packaged.
 *
 * It is the "upstream" for course 07 of the Nix mastery path: learners
 * package it in a nixpkgs checkout exactly as they would package real
 * software. It has no dependencies beyond a C compiler and libc.
 */
#include <stdio.h>
#include <string.h>

#ifndef GREET_VERSION
#define GREET_VERSION "unknown"
#endif

static void usage(FILE *out)
{
    fprintf(out,
            "Usage: greet [--version | --help]\n"
            "Print a friendly greeting.\n");
}

int main(int argc, char **argv)
{
    if (argc == 1) {
        printf("Hello from greet %s\n", GREET_VERSION);
        return 0;
    }
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        printf("greet %s\n", GREET_VERSION);
        return 0;
    }
    if (argc == 2 && strcmp(argv[1], "--help") == 0) {
        usage(stdout);
        return 0;
    }
    usage(stderr);
    return 2;
}
