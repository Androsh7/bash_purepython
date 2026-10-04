# Bash_PurePython

PurePython implementations of common bash commands, for use with pyodide.

These are mostly vibe coded, use at your own risk.

## Embedding the shell

`bash_purepython.shell` runs these commands behind a bash-like line syntax
without a subprocess, which is what the browser terminal on androsh7.com uses
under Pyodide.

```python
from bash_purepython.shell.models import HostCommand
from bash_purepython.shell.session import ShellSession

session = ShellSession(home="/home/user", host_commands=[HostCommand("vim", "open a file")], environment={})
result = session.run_line("echo hello | tr a-z A-Z > out.txt && cat out.txt")
print(result.stdout, result.exit_code, result.cwd)
completion = session.complete("gre", cursor=3)
print(completion.replacement)
```

Commands the embedding host runs itself (an editor, a network fetch, a file
upload) are declared as `HostCommand`s. The session reports them back as a
`host_call` instead of running them, and refuses them inside a pipeline.
`bash_purepython.shell.bridge` wraps the same calls in JSON strings for hosts
that cannot pass Python objects.
