Real ELF relocatables for the Linux receipt's `.comment` rule (`tools/test_native_provenance.py`).

- `data-only-incbin.x86_64.o`: `data-only-incbin.S` assembled the way Chromium assembles ICU's `icudtl.dat`. The data goes into `.rodata` with `.incbin`, `.text` is empty, and there is no `.comment`. The included blob is the 256 bytes 0x00..0xff.
- `code-no-ident.x86_64.o`: `code-no-ident.c` compiled with `-fno-ident`. It holds code and has no `.comment`, so it must still be refused.

Regenerate from this directory:

    python3 -c 'open("blob.dat","wb").write(bytes(range(256)))'
    clang --target=x86_64-linux-gnu -c data-only-incbin.S -o data-only-incbin.x86_64.o
    clang --target=x86_64-linux-gnu -O2 -fno-ident -c code-no-ident.c -o code-no-ident.x86_64.o
    rm blob.dat
