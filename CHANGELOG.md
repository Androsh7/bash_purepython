# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.3.0 - 2026-10-03

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
- Behavioural tests for the shell under `tests/shell`

### Changed

- Ruff targets Python 3.11 and the publish workflow builds on 3.11, matching
  `requires-python`

### Fixed

- `print_error` and `print_warning` wrote to stdout, so an error from one
  command in a pipeline was fed to the next; they now write to stderr
- `help` listed subpackages as if they were commands
- The wheel only packaged the top-level package, so subpackages were left out

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
