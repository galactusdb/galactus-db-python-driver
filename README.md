# Galactus Python driver

[Galactus DB website](https://galactusdb.com) · [Source](https://github.com/galactusdb/galactus-db-python-driver) · [Type mapping](docs/BLUEPRINT.md) · [Spatial types](docs/SPATIAL.md)

Native Bolt 4.4 driver for Galactus DB. This experimental 0.1 implementation
has zero third-party runtime package dependencies. Source is available here;
no npm, NuGet, PyPI, Maven Central, or crates.io release is implied.

## How To

### 1. Get the driver

```sh
git clone --branch main https://github.com/galactusdb/galactus-db-python-driver.git
cd galactus-db-python-driver
```

Python 3.10+; no runtime dependencies. Setuptools is only needed to build/install the package.

```sh
python -m pip install .
```

### 2. Configure your connection

Start or obtain a Galactus DB instance; visit [galactusdb.com](https://galactusdb.com)
for database information. Use its Bolt address (locally, `bolt://127.0.0.1:7687`),
username, and configured password. The example reads `GDB_PASSWORD` from your
environment; it is an application variable, not a command to change the server password.

```sh
# Bash / zsh
export GDB_PASSWORD='your-database-password'
```

```powershell
# PowerShell
$env:GDB_PASSWORD = 'your-database-password'
```

### 3. Execute a parameterised query

```python
import os
from galactus import Driver, Spatial, Point2D

with Driver("bolt://127.0.0.1:7687", "gdb", os.environ["GDB_PASSWORD"]) as driver:
    result = driver.execute_query("RETURN $name AS name", {"name": "Ada"})
    print(result.records[0]["name"])
    print(result.summary)
```

Optional constructor keywords: `database="neo4j"`, `timeout=30` (seconds).
`bolt+s://` validates certificates and hostnames with system trust roots.

`begin(read_only=False)`, `commit()`, `rollback()`, and `close()` are explicit.
The context manager closes the connection and rolls back unfinished work; it
does **not** implicitly commit. Use one driver per worker.

Native int, float, bool, str, bytes, lists and string-keyed dicts map both ways.
Standard date/time inputs work directly. Returned temporals use native objects
where lossless and named immutable values when nanoseconds exceed Python's
precision. Points, graph values, calendar durations and spatial envelopes have
named types. Use a node's `.properties` or `.id` as input, not the node itself.

See [mapping details](docs/BLUEPRINT.md), [spatial examples](docs/SPATIAL.md), and
[the common limitations](docs/OVERVIEW.md#scope-of-01).

### 4. Run the tests

From this repository's root:

```sh
python tests/test_driver.py
```

See [test instructions](tests/README.md) for prerequisites and opt-in live tests.
Connection failures discard the connection; writes are never automatically retried.
Results are eager and each driver owns one connection; see the documented scope.

Learn more at [Galactus DB website](https://galactusdb.com).
