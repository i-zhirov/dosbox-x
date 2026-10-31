#!/bin/sh
# Build the agent test fixtures with nasm.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
nasm -f bin -o "$DIR/fixture/re_loop.com" "$DIR/fixture/re_loop.asm"
nasm -f bin -o "$DIR/fixture/re_fixture.com" "$DIR/fixture/re_fixture.asm"
nasm -f bin -o "$DIR/fixture/re_fileio.com" "$DIR/fixture/re_fileio.asm"
nasm -f bin -o "$DIR/fixture/re_input.com" "$DIR/fixture/re_input.asm"
nasm -f bin -o "$DIR/fixture/re_screen.com" "$DIR/fixture/re_screen.asm"
nasm -f bin -o "$DIR/fixture/re_int15.com" "$DIR/fixture/re_int15.asm"
ls -la "$DIR/fixture/"*.com
