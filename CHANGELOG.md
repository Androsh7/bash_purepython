# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.4.0

### Added

- `bash_purepython.execute_command`, an asyncio execution engine for bash-like scripts: lazily streaming
  pipelines, `&&`/`||` lists, `if`/`for`/`while`/`until`, functions, subshells, brace groups, background jobs
  (`&`, `$!`, `ps`, `kill`, `wait`, `jobs`), redirections, heredocs, parameter and command substitution
- `bash_purepython.pyodide_session`, the host-facing session for a browser terminal: `PyodideSession` keeps one
  shell state and executor across calls, `run` returns the exit code, directory and variables as JSON,
  `HostCommand` relays a command the host implements through the pipeline so it can be piped and redirected,
  and the Python REPL is Pyodide's own console (`repl_start`, `repl_feed`, `repl_complete`)
- The coreutils ported onto the `Command` interface: `basename`, `cp`, `cut`, `date`, `dirname`, `env`, `find`,
  `grep`, `gzip`, `gunzip`, `help`, `ls`, `mkdir`, `mv`, `nl`, `pwd`, `realpath`, `rev`, `rm`, `rmdir`, `seq`
- Pathname expansion: an unquoted `*`, `?` or `[...]` in a word is replaced by the paths it matches, in
  sorted order, so `rm *` and `for f in *.txt` work. A pattern that matches nothing stays literal, hidden
  files match only a pattern that names the leading dot, and quoting or escaping keeps a wildcard literal
- Arithmetic: `$(( expression ))` expands to its value and `(( expression ))` is a command that succeeds
  when the value is nonzero. Integers in decimal, octal, hexadecimal and `base#digits` form, variables
  by bare name, every C operator bash has including `**`, `?:`, `,`, assignment and `++`/`--`, with
  division truncating toward zero and the untaken side of `&&`, `||` and `?:` left unevaluated
- `test` and `[`: string and integer comparisons, `-z`/`-n`, the file tests `-e -f -d -L -h -s -r -w -x`,
  `-nt`/`-ot`/`-ef`, and `!`, `-a`, `-o` and parentheses, exiting two on a malformed expression
- `grep -q` (`--quiet`, `--silent`) prints nothing and stops at the first match
- `CommandInvocation.attached_to_terminal` tells a command that nothing stands between it and the
  terminal: no pipe, capture or redirection on either output stream. A host command is told the same,
  so it may write to the terminal as it runs, which is what lets a prompt show before it blocks on input
- A host command receives the input piped or redirected into it (`echo x | cmd`, `cmd < file`,
  `cmd <<< text`) and the shell's current directory, and `PyodideSession.repl_discard` drops a block the
  console is still waiting to see finished

### Removed

- The standalone coreutils scripts and `bash_purepython.shell` (tokenizer, parser, builtins, completion,
  `ReplSession` and the JSON bridge); the engine and session above replace them. Shell completion and
  multi-line continuation are now the host's job

## 0.3.0

### Added

- `bash_purepython.shell`, a shell layer for embedding the commands: a tokenizer
  with bash-style quoting, `$VAR`, `${VAR}`, `$?` and `~` expansion, a parser
  for pipelines (`|`), command lists (`&&`, `||`, `;`) and redirection (`>`,
  `>>`), and a `ShellSession` that runs lines in-process with captured streams
- Shell builtins `cd`, `export`, `history`, `which`, `help`, `uname` and `clear`
- Tab completion for command names, file paths and the options of every
  command, with quoting reapplied to the completed word
- `ReplSession`, an interactive Python session with CPython-style Tab handling:
  indent on a blank prefix, otherwise complete names with `rlcompleter`
- `bash_purepython.shell.bridge`, a JSON facade for hosts such as Pyodide
- An output sink: with one set, the last command's stdout and every stderr stream to
  the host as they are written instead of being collected, redirected output goes
  straight to the file, and a `KeyboardInterrupt` raised in a command exits 130
- `$?` is resolved per pipeline, so `false; echo $?` prints 1 on the same line
- `cd -` returns to the previous directory and fails when there is none
- Wildcards: unquoted `*`, `?` and `[...]` match files in sorted order, a pattern that matches nothing stays
  literal, hidden files match only a pattern that names the leading dot, and quoting keeps a pattern literal
- Here-documents (`cmd << EOF`, `<<-` to strip leading tabs, a quoted delimiter to stop `$VAR` expanding),
  quoted strings spanning lines, and backslash line continuation. `ShellSession.needs_more` tells a host
  whether the lines so far are still waiting for a quote or delimiter to close
- stderr and input redirection: `2> file`, `2>> file`, `2>&1`, `&> file` and `< file`; `1>` is plain stdout, and
  descriptor forms the shell cannot honour (`3>`, `>&2`, `2>&3`) are refused with a message naming them
- Variables expand per pipeline, so `export FOO=bar; echo $FOO` and `cd sub; echo $PWD` work on one line
- Ctrl-C aborts the whole line, not just the command it landed in
- Tab completion takes the cursor in UTF-16 units, as a browser host sends it, so emoji on the line no longer break it
- Behavioural tests for the shell under `tests/shell`

- `ls -h` (`--human-readable`) prints sizes like 1.5K and 12M in a long listing; help is `--help`

### Changed

- Ruff targets Python 3.11 and the publish workflow builds on 3.11, matching
  `requires-python`

### Fixed

- `print_error` and `print_warning` wrote to stdout, so an error from one
  command in a pipeline was fed to the next; they now write to stderr
- `help` listed subpackages as if they were commands
- `ls -r` used a Python 3.13-only argument, so it failed on 3.11 and 3.12
- `ls` given a file path tried to list it as a directory and failed
- `sleep` could not be interrupted under Pyodide, where one long `time.sleep` blocks the worker; it now sleeps in short slices
- `yes` swallowed a `KeyboardInterrupt` and exited 0; it now exits 130 like the real one
- A command whose redirect target could not be opened still ran; it is now skipped
- Adjacent operators such as `;;` were silently accepted as a success; they are a syntax error
- An error stream that reached the limit was truncated silently with exit 0; it is now an error
- `ls -h` rounds up and steps to the next unit the way GNU ls does, so 1048575 bytes is 1.0M
- Completion inside double quotes dropped backslashes the shell keeps
- The wheel only packaged the top-level package, so subpackages were left out
- Inside double quotes a backslash escaped every character; it now escapes only `$`,
  `"`, `\` and backtick, so `grep "\.txt"` keeps its backslash
- A pipe buffer that reached its limit (now 256 MiB) truncated silently with exit 0;
  it is now an error on stderr with exit 1
- A line that expanded to nothing was a syntax error instead of a no-op
- The result environment carried every process variable and a stale `PWD`; it now
  holds only variables the shell was seeded with or exported, and `HOME` is honoured
  by `cd` and `~` when exported
- Completion of a bare `~` and of `$VAR/...` paths
- The REPL is built on `code.InteractiveInterpreter`: tracebacks show only the user's
  frames, `exit` inside a block is code, a `KeyboardInterrupt` is reported rather than
  propagated, and partial output is flushed before each reply

## 0.2.0

### Added

- `find`, with `-name`, `-iname`, `-type`, `-maxdepth` and `-mindepth`
- `tree`, with `-a`, `-d` and `-L`

### Fixed

- `touch` took a single path, so `touch a b c` failed with an argument error
- `touch` refused to touch a file that already existed unless `-f` was given,
  rather than updating its timestamp. `-f` is now accepted and ignored, and
  `-c` skips creating files that are missing

## 0.1.2 - 9/8/2026

### Fixed

- PyPi build

## 0.1.1

### Fixed

- Module pathing

## 0.1.0

### Added

- PurePython implementations of basic bash commands
- 
