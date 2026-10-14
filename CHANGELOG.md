# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.5.0

### Added

- `bash_purepython.continuation.script_needs_more_lines`, which tells an interactive host whether the lines
  typed so far leave a quote, heredoc, `$( )`, group, `[[ ]]` or compound command open or end in `\`, `|`,
  `&&` or `||`, so it can prompt for another line; `PyodideSession.needs_more` exposes it and the example
  terminal uses it in place of its own check. The live suite compares it with `bash -n` on each fragment
- Commands ported from the old scripts onto the `Command` interface: `sort`, `tail`, `tar`, `tee`, `touch`,
  `tr`, `tree`, `uniq`, `unzip`, `wc`, `which`, `whoami`, `zip`
- New commands: `base64`, `chmod`, `column`, `df`, `diff`, `du`, `expr`, `file`, `fold`, `hostname`, `id`,
  `less`, `md5sum`, `mktemp`, `more`, `od`, `paste`, `sed` (`s///` with flags and groups, `-n`, `-e`, `-E`,
  `-i`, `p`, `d`, `q`, `=`, `a`, `i`, `c`, `y`, groups, line, regex and range addresses), `sha1sum`,
  `sha256sum`, `sha512sum`, `stat`, `uname`, `xxd`
- Builtins: `read` (`-r`, `-p`, `-a`, `-d`, `-n`, one line at a time from a pipe, here-string, file or the
  host's terminal), `shift`, `set` (`--`, `-e`, `-u`, `-x`, `-o pipefail`), `local`, `eval`, `type`,
  `command`, `alias`, `unalias`, `pushd`, `popd`, `dirs`, `let`, `declare`, `typeset`, `readonly`, `hash`,
  `xargs` (`-n`, `-I`, `-0`, `-d`, `-t`), and `printf -v`. `exec`, `trap` and `getopts` say they are not
  supported instead of being unknown
- `select` loops, with the menu and `PS3` prompt on standard error, bash's column layout, `REPLY`, and an
  empty line showing the menu again
- Process substitution `<( )` and `>( )`, backed by a temporary file that is removed once the command's
  block has finished
- Syntax: `>&2`, `1>&2`, `>&1`, `2>&2`, `>&-` and `2>&-`; `case`/`esac` with `;;`, `;&` and `;;&`;
  `for (( ; ; ))`; brace expansion (`{a,b}`, `{1..5}`, `{01..03}`, `{a..e}`, `{1..10..2}`, nested);
  ANSI-C quoting `$'...'`; `IFS` word splitting; the parameter operators `${x#} ${x##} ${x%} ${x%%}
  ${x/} ${x//} ${x/#} ${x/%} ${x^} ${x^^} ${x,} ${x,,} ${!x} ${x:offset:length}`; indexed arrays
  (`a=(1 2)`, `a+=(3)`, `a[5]=x`, `${a[i]}`, `${a[@]}`, `"${a[@]}"`, `${#a[@]}`, `${!a[@]}`, slices and
  operators on `[@]`, `unset a[i]`, `BASH_REMATCH` from `[[ =~ ]]`); `$$`, `$PPID`, `$RANDOM`, `$SECONDS`,
  `$SHELL` and `$BASH_VERSION`
- Options on existing commands: `head -n -N`, `cat -v -A -E -T -e -t -s -b`, `env -i -u NAME=VALUE`,
  `grep -o -w -x -A -B -C -r`, `ls -R` in GNU layout, `kill %N`, `wait %N`
- `help` prints a one-line summary next to every command, builtin and host command; `help -s` prints the
  names alone. Every `Command` declares a `summary`
- `cd -` prints the directory it returns to, and `jobs` prints bash's `[1]+  Running` layout

### Fixed

- A here-document inside `$( )` belongs to the command in the substitution instead of being run as commands
- A builtin whose output is redirected or piped (`jobs > f`, `eval 'echo x' | cat`) now sends it there
  rather than straight to the terminal
- Files written by `>` and `>>` keep `\n` line ends on Windows hosts instead of gaining `\r\n`
- The engine exits with 127 on an unbound variable under `set -u`, as bash does
- A positional parameter that was never given counts as unset, so `${1-default}`, `${1?message}` and
  `set -u` behave as in bash; a negative array subscript counts back from the highest index of a sparse array
- `declare -a name=(...)` and `local -a name=(...)` populate the array instead of receiving `name=`
- The word `case` as an argument inside a `case` clause no longer opens a nested statement
- `head` run with nothing piped in exits cleanly instead of aborting the script
- `sort` honours the `r` modifier on a `-k` key; `read -d ''` reads to the end of the input
- `zip` adds to an existing archive, accepts absolute sources, skips itself under `-r .` and reports a
  missing archive directory; `unzip` and `tar` report encrypted, corrupt or truncated archives instead of
  crashing; `tar -c` reports a missing archive directory
- `sed -i` keeps `\r\n` line ends in the edited file and the backup; `a`, `i` and `c` text may continue into
  the next `-e`, so `sed '$a\'` adds a missing final newline
- `chmod` accepts permission copies (`g=u`) and several operators in one clause (`u+x-w`), and reports a
  dangling symlink under `-R` instead of crashing

### Changed

- `grep` patterns are POSIX basic regular expressions, extended with `-E`, rather than Python regular
  expressions, so `grep 'f(x)'` matches the literal text
- A `$( )` substitution that reaches the executor's output limit, such as `echo "$(yes)"`, now fails the
  command with an error instead of continuing with the truncated output
- A `NAME=value` prefix on a command is exported to that command only, and `env` prints only exported
  variables

- `PyodideSession` accepts the host commands as a mapping of names to summaries as well as a list, and
  gives the shell state a `read_line` callback that reads the terminal through standard input
- The splitter no longer reads `name=(...)` as a function definition

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
- `[[ expression ]]`: operands are not word-split or expanded into file names, the right side of `==`
  and `!=` is a pattern and of `=~` a regular expression with quoted parts literal, numeric operators
  evaluate arithmetic, and `&&`, `||`, `!`, `<`, `>` and parentheses belong to the expression, with
  the undecided side of `&&` and `||` left unexpanded
- `ls` prints what GNU ls does: `-l` gives a `total` line and mode, links, owner, group, size, time and
  name for each entry, `-a` includes `.` and `..`, and `-A`, `-r`, `-t`, `-S`, `-1`, `-d`, `-s` and `-F`
  exist, so clusters such as `-lah`, `-ltr` and `-lsa` parse. Named files are listed before named
  directories, and names come one per line when the output is not the terminal

- Script files: `bash` and `sh` run a file, the text after `-c`, or a script from standard input against
  a copy of the state with its own positional arguments; a command name holding a slash runs that file
  the same way; `source` and `.` run a file against the live state and honour `return`. A script's
  output pipes, redirects and captures like any command's, and a missing file exits 127, or 1 when
  sourced
- `ShellState.exported_names` records what `export` marked, `unset` clears it, and
  `exported_variables()` returns what a new process would inherit
- `examples/terminal.py`, an interactive terminal on the engine showing what a host supplies

### Changed

- `PyodideSession.run` reports only exported variables as the environment, not every shell variable
- `PyodideSession` moves the process into the shell's directory for the length of a host command and
  back afterwards, instead of following every `cd`, so a `cd` inside a subshell no longer leaks
- `ls -r` reverses the order, as in GNU ls; recursion is `-R` only
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
