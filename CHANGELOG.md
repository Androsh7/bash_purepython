# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.3.1

### Fixed

- A redirect target set by an `export` earlier on the same line (`export F=out.txt; echo hi > $F`)
  was refused as an ambiguous redirect before anything ran; the host-command check now expands
  only command names, so the line runs and the file is written
- A stage that hit the pipe limit while its stderr went to a file or shared the pipe (`yes 2> err`,
  `yes 2>&1 | head -n 1`) raised out of `run_line` instead of reporting the overflow; the notice
  now goes to the line's collected stderr with exit code 1
- A wildcard inside double quotes followed by an escape (`"*\$x"`) could still expand against
  the directory; text before the escape now stays quoted

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
