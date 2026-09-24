# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
