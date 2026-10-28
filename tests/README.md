# galactus-db-python-driver tests

[Galactus DB website](https://galactusdb.com) · [Driver Quickstart](../README.md)

## Quickstart

Run these commands from the repository root:

```sh
python tests/test_driver.py
```

The fixtures are included in `tests/fixtures`; no sibling repository is needed.
The tests use standard runtime/test facilities, with no test framework packages.
The wire fixtures cover integer boundaries, UTF-8, temporal values, graph values,
points, malformed inputs and unknown structures. `values.tsv` round-trips in Bolt
4.4 mode and `bolt5.tsv` (element ids, datetime tags `I`/`i`, named zones with a
local or UTC basis) in Bolt 5 mode. Each row of `datetime_pairs.tsv` holds the
same instant as Bolt 4.4 `F` and Bolt 5 `I`: both decode to equal values, and the
encoder writes the first form in 4.4 mode and the second in Bolt 5 mode. The
spatial fixture contains 57 geometry/geography cases, including XY/XYZ, empties,
holes, multipart shapes, nested collections, and antimeridian geography.

### Live database tests

Without `GDB_TEST_URI`, live tests are skipped. To include them, start a **fresh,
disposable** Galactus database and set these environment variables before running
the same test command:

```sh
export GDB_TEST_URI='bolt://127.0.0.1:7687'
export GDB_TEST_PASSWORD='your-disposable-database-password'
```

```powershell
$env:GDB_TEST_URI = 'bolt://127.0.0.1:7687'
$env:GDB_TEST_PASSWORD = 'your-disposable-database-password'
```

Optional variables:

| Variable | Effect |
|---|---|
| `GDB_TEST_EXPECT_BOLT` | Asserts the agreed protocol, for example `5.4`, or `4.4` against a server started with `GDB_BOLT_MAX_VERSION=4.4` |
| `GDB_TEST_CA_FILE` | PEM CA for a `bolt+s://` URI; passed as `trusted_certificates`, and enables the check that connecting without it fails verification |

Tests use username `gdb` and the server's default database. They create
test-labelled nodes and a unique constraint on `DriverPythonUnique`, and exercise
commit/rollback, element ids, offset and named-zone datetimes, decimals, recovery
after a failed query inside and outside a transaction, error classification on a
constraint violation, certificate trust and rejected authentication. Do not point
them at valuable data. Reset the disposable database between runs because the
tests leave nodes and a constraint behind.

The workspace runner (`tests/run_live.py` in the drivers workspace) starts
disposable servers and runs this suite three times: Bolt 5.4, a server capped at
Bolt 4.4, and the server's own TLS with a throwaway CA. See
[implementation scope](../docs/OVERVIEW.md#scope-of-02).

Database information: [Galactus DB website](https://galactusdb.com).
