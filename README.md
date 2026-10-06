# Bash_PurePython

PurePython implementations of common bash commands, for use with pyodide.

These are mostly vibe coded, use at your own risk.

## Running scripts

`bash_purepython.execute_command` runs bash-like scripts in-process, with no
subprocesses or threads, which is what pyodide needs. A script is split into
top-level blocks, each block is turned into a plan, the plan is executed, and
any script text found along the way (loop bodies, function bodies, `$( )`
substitutions, subshells) re-enters the same loop.

```python
from bash_purepython.execute_command import run_script
from bash_purepython.shell_state import ShellState

state = ShellState.for_terminal()
exit_code = run_script("yes | head -n 3; echo $(echo sub) | cat", state)
print(state.stdout, state.stderr, exit_code)
```

Pipelines stream lazily: a command declares the kinds of input and output it
supports (`Iterator[str]`, `str`, `Iterator[bytes]`, `bytes`) and the engine
negotiates a shared kind between neighbouring stages, so `yes | head` runs
`yes` only as far as `head` reads. Standard output and standard error are
written to the state's sinks as each chunk is produced and are also recorded
on the state.

Pass `write_output=` and `write_error=` callables to `ShellState` to receive
the streams somewhere other than the process streams. Register extra commands
by subclassing `bash_purepython.command.command.Command` and adding an
instance to a `CommandRegistry` passed to `run_script`.

Supported so far: pipelines (`|`, `|&`, `!`), `&&`/`||` lists, `if`/`elif`/`else`,
`for`, `while`, `until`, functions, subshells, brace groups, redirections
(`>`, `>>`, `<`, `2>`, `2>>`, `2>&1`, `&>`, heredocs, here-strings), parameter
and command substitution, and the builtins `cd`, `export`, `unset`, `exit`,
`return`, `break`, `continue`. Background `&` runs the command synchronously.
Not yet: `case`, `select`, globbing, arithmetic, process substitution.
