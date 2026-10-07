# Bash_PurePython

PurePython implementations of common bash commands, for use with pyodide.

These are mostly vibe coded, use at your own risk.

## Running scripts

`bash_purepython.execute_command` runs bash-like scripts on asyncio, with no
subprocesses or threads, which is what pyodide needs. A script is split into
top-level blocks, each block is turned into a plan, the plan is executed, and
any script text found along the way (loop bodies, function bodies, `$( )`
substitutions, subshells) re-enters the same loop.

Under pyodide, where an event loop is already running, await the entry point
(for example from `runPythonAsync` with top-level `await`):

```python
from bash_purepython.execute_command import run_script_async
from bash_purepython.shell_state import ShellState

state = ShellState.for_terminal()
exit_code = await run_script_async("yes | head -n 3; echo $(echo sub) | cat", state)
print(state.stdout, state.stderr, exit_code)
```

On CPython, `run_script(script, state)` drives its own loop, and `ShellRunner`
keeps one loop alive across calls so background jobs survive between them.

Pipelines stream lazily: a command declares the kinds of input and output it
supports (`Iterator[str]`, `str`, `Iterator[bytes]`, `bytes`, synchronous or
asynchronous) and the engine negotiates a shared kind between neighbouring
stages, so `yes | head` runs `yes` only as far as `head` reads. A group, loop,
conditional or function used as a pipeline stage runs as its own task and
streams through a bounded queue, so `( yes ) | head -n 2` terminates too.
Standard output and standard error are written to the state's sinks as each
chunk is produced and are also recorded on the state. A sink may be an async
callable, such as a JavaScript function, and is awaited per chunk.

`cmd &` starts a background job on the event loop. `$!` holds its pid, the
fake `ps` lists the job table (`R` running, `D` done, `K` killed), `kill PID`
cancels a job, `wait [PID]` waits and reaps, and `jobs` lists them bash-style.

Register extra commands by subclassing `bash_purepython.command.command.Command`
and adding an instance to a `CommandRegistry`. A command's `run` may be a plain
function or a coroutine, so it can await a browser promise such as `fetch`.

Supported so far: pipelines (`|`, `|&`, `!`), `&&`/`||` lists, `if`/`elif`/`else`,
`for`, `while`, `until`, functions, subshells, brace groups, background jobs,
redirections on commands and on compound commands (`>`, `>>`, `<`, `2>`, `2>>`,
`2>&1`, `&>`, heredocs, here-strings, `/dev/null`), parameter and command
substitution, pathname expansion (`*`, `?`, `[...]`), and the builtins `cd`, `export`, `unset`, `exit`, `return`,
`break`, `continue`, `wait`, `jobs`.
Commands shipped: `basename`, `cat`, `cp`, `cut`, `date`, `dirname`, `echo`,
`env`, `false`, `find`, `grep`, `gunzip`, `gzip`, `head`, `help`, `kill`, `ls`,
`mkdir`, `mv`, `nl`, `printf`, `ps`, `pwd`, `realpath`, `rev`, `rm`, `rmdir`,
`seq`, `sleep`, `true`, `yes`. Every command takes `--help`; `-h` is left free
for the commands that use it, such as `ls -h` and `grep -h`.

Known limitations: `case`, `select`, arithmetic and process substitution are
not implemented; a `$( )` substitution that never stops
writing is cut off at the executor's output limit.

## Testing

`uv run pytest` runs the in-memory suite. `tests/test_live_bash.py` runs the
same several hundred scripts through a real `bash` binary and the engine and
compares standard output and exit codes; it is marked `live_bash_test` and
excluded by default. Run it with:

```bash
uv run pytest -m live_bash_test
```
