#!/bin/sh
# Build the agent test fixture with nasm.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
nasm -f bin -o "$DIR/fixture/re_loop.com" "$DIR/fixture/re_loop.asm"
ls -la "$DIR/fixture/re_loop.com"
