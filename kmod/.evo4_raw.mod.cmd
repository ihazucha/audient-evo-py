savedcmd_evo4_raw.mod := printf '%s\n'   evo4_raw.o | awk '!x[$$0]++ { print("./"$$0) }' > evo4_raw.mod
