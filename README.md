# Galactus DB Python Driver

[Galactus DB](https://galactusdb.com) · [Driver catalogue](https://galactusdb.com/product/drivers) · [Type mapping](docs/BLUEPRINT.md) · [Spatial guide](docs/SPATIAL.md) · [Issues](https://github.com/galactusdb/galactus-db-python-driver/issues)

Connect Python applications to Galactus DB with parameterised Cypher,
native values, and explicit transactions. The driver speaks Bolt 5.4 directly,
falls back to Bolt 4.4 when the server asks for it, verifies TLS against the
server's certificate, and has **zero third-party runtime package dependencies**.

**Status: 0.2 / early access.** Source is available on `main`. This is a tested
baseline with one connection per driver and eager results, installed from source
as shown below. Check the [current scope](#current-scope) against your application.

## Contents

- [Quickstart](#quickstart)
- [Connection configuration](#connection-configuration)
- [Queries and results](#queries-and-results)
- [Transactions](#transactions)
- [Native type mapping](#native-type-mapping)
- [Spatial values](#spatial-values)
- [Errors and connection lifecycle](#errors-and-connection-lifecycle)
- [Testing](#testing)
- [Current scope](#current-scope)

## Quickstart

### 1. Get the source

Requirements: **Python 3.10+**, Git, and a reachable Galactus DB instance.

```sh
git clone --branch main https://github.com/galactusdb/galactus-db-python-driver.git
cd galactus-db-python-driver
```

Run this in the driver checkout.

```sh
python -m pip install .
```

Setuptools is a build dependency only. For a source checkout, running Python from the repository root also makes `galactus` importable without installation.

Git-based installs follow `main`; pin a reviewed commit in your application for
reproducible builds. No npm, NuGet, PyPI, Maven Central or crates.io availability
is implied by the package names.

### 2. Configure your database credentials

Start Galactus DB on your infrastructure using the setup available from
[galactusdb.com](https://galactusdb.com). The examples use
`bolt://127.0.0.1:7687` and username `gdb`; replace them with your server settings.
Set your configured password in the application environment:

```sh
# Bash / zsh
export GDB_PASSWORD='your-database-password'
```

```powershell
# PowerShell
$env:GDB_PASSWORD = 'your-database-password'
```

`GDB_PASSWORD` is read by these examples; the driver does not automatically load
environment variables or change the server password. Keep credentials out of
source control and connection URIs.

### 3. Run your first query

```python
import os
from galactus import Driver, Spatial, Point2D

with Driver("bolt://127.0.0.1:7687", "gdb", os.environ["GDB_PASSWORD"]) as driver:
    result = driver.execute_query("RETURN $name AS name", {"name": "Ada"})
    print(result.records[0]["name"])
    print(driver.protocol_version, driver.server_agent)
```

The following examples reuse an open `driver` within the same resource scope.
Adapt error handling to your application.

## Connection configuration

`Driver(uri, username, password, database="", timeout=30, trusted_certificates=None)`;
timeout is seconds. The context manager closes the connection.

| Setting | Behaviour |
|---|---|
| URI | Direct `bolt://host:port` or verified TLS `bolt+s://host:port`; omitted port is 7687 |
| Authentication | Required username and password; no credentials in the URI |
| Database | Empty/omitted database delegates selection to the server’s configured default |
| Named database | Supply an existing database name explicitly, for example `app` |
| Timeout | Default examples use 30 seconds; see the language-specific units above |
| Trusted certificates | Path to a PEM file of CA or server certificates used instead of the system store; `bolt+s://` only |
| Result handling | Records are buffered in memory until the query completes |

After connecting, `protocol_version` holds the agreed Bolt version (`"5.4"` or
`"4.4"`), `server_agent` and `connection_id` come from the server's greeting, and
`last_bookmark` holds the most recent bookmark returned by an autocommit query or
commit.

### TLS

Galactus DB serves TLS itself when it is started with a certificate and key
(`GDB_TLS_CERT` and `GDB_TLS_KEY`), on the same port. Connect with `bolt+s://`
and the driver checks the certificate chain and the host name from the URI using
Python's `ssl` module and the system trust store:

```python
driver = Driver("bolt+s://db.example.com:7687", "gdb", os.environ["GDB_PASSWORD"])
```

For a private CA or a self-signed development certificate, pass the PEM file
that should be trusted:

```python
driver = Driver(
    "bolt+s://localhost:7687", "gdb", os.environ["GDB_PASSWORD"],
    trusted_certificates="certs/dev-ca.pem",
)
```

Verification is always on, and a `bolt+s://` connection never falls back to
plaintext. Setting `trusted_certificates` on a `bolt://` URI raises `ValueError`.

Timeouts bound socket waits, not necessarily total query duration or DNS lookup;
Go uses a deadline for the complete operation. Use one driver per worker; a driver is not safe for concurrent use.

## Queries and results

Bind data as parameters, never interpolate user input into Cypher:

```python
result = driver.execute_query(
    "CREATE (p:Person {name:$name, age:$age}) RETURN p.name AS name, p.age AS age",
    {"name": "Ada", "age": 37},
)
print(result.records[0]["name"])
print(result.summary)
```

Results expose column keys, records indexed by column name, and server summary
metadata. Read a column with `result.records[0]["name"]`. Use unique column aliases because
records are maps. Summary fields can include the database, query classification,
timings, bookmark and update statistics; only fields supplied by the server are
present. A query without rows still returns its summary.

Lists and maps can be nested. Values are recursively encoded and hydrated,
including graph properties and spatial envelopes. Use Cypher `LIMIT` or
application-level pagination for large result sets: this release is eager,
not a lazy streaming cursor.

## Transactions

Queries outside an explicit transaction autocommit. Group related writes with
begin/commit; explicitly roll back when abandoning work:

```python
driver.begin()
driver.execute_query("CREATE (:Person {name:$name})", {"name": "Ada"})
driver.execute_query("CREATE (:Person {name:$name})", {"name": "Grace"})
driver.commit()
# To deliberately abandon an open transaction: driver.rollback()
```

The transaction belongs to the connection. Keep both statements on the same
driver and finish the transaction before reusing it for unrelated work. Closing
or disposing a connection rolls back an unfinished transaction; it never
implicitly commits. The read-only argument requests a read transaction.

If the database rejects a statement inside a transaction, the server rolls the
transaction back and the driver raises `DatabaseError`; `driver.in_transaction`
is then `False` and the same driver is ready for the next query. A rejected
COMMIT means the transaction did not commit. A lost connection during COMMIT can
mean the commit outcome is unknown; reconcile the result before retrying a write.

## Native type mapping

`int`, `float`, `bool`, `str`, `bytes`, `list`, and string-keyed `dict`. Native `date`, `time`, `datetime`, and `timedelta` inputs work directly. Returned temporals use native objects where lossless and named immutable values where nanoseconds exceed native precision.

- Database integers are signed 64-bit; out-of-range integer inputs fail.
- Bytes stay binary; values do not pass through JSON.
- Temporal wrappers preserve nanoseconds, offsets and named zones when the
  runtime’s native types cannot represent the full value.
- Calendar duration keeps months, days, seconds and nanoseconds separately.
- Graph nodes, relationships and paths have named result types. Nodes and
  relationships carry `element_id` (and `start_element_id` / `end_element_id` on
  relationships) as strings, matching Cypher's `elementId()`. Bind their IDs or
  properties as parameters; the graph entities themselves are result-only.
- `DECIMAL` values arrive as strings holding their exact digits. Send a
  `decimal.Decimal` (or a string) and convert it in Cypher with `decimal($d)`;
  the driver sends the exact plain digits and rejects NaN and infinities.
- `ZonedDateTime` keeps the IANA zone name and records whether its seconds are
  local or UTC (`ZonedDateTime.local(...)`, `ZonedDateTime.utc(...)`). Aware
  `datetime` inputs are sent with their resolved offset.
- Unknown wire structures remain explicit structures and cannot be used as
  generic application-object serialization.

No ORM or automatic arbitrary-object mapping is included. Convert application
models and UUIDs explicitly to a supported format.

```python
from decimal import Decimal

price = driver.execute_query("RETURN decimal($d) AS d", {"d": Decimal("12.30")}).records[0]["d"]
print(Decimal(price))  # 12.30
```
See the [complete type mapping](docs/BLUEPRINT.md) for precision and range details.

## Spatial values

The driver supports `Point2D`, `Point3D`, and a native `Spatial` value covering
every shape family currently supported by Galactus DB:

| Shape family | Geometry | Geography |
|---|---|---|
| Point / LineString / Polygon, including holes | Yes | Yes |
| MultiPoint / MultiLineString / MultiPolygon | Yes | Yes |
| GeometryCollection, including nested collections | Yes | Yes |
| XY, XYZ, and typed empty shapes | Yes | Yes |

`Spatial` preserves WKB bytes together with domain, SRID, coordinate layout and
model. Geometry uses `planar`; geography uses `greatCircle`. Neither domain nor
SRID is inferred by converting through GeoJSON.

```python
shape = driver.execute_query(
    "RETURN spatial.fromWKT($wkt, {domain:$domain}) AS shape",
    {"wkt": "POLYGON((0 0,4 0,4 4,0 4,0 0))", "domain": "geometry"},
).records[0]["shape"]
driver.execute_query(
    "CREATE (:Region {name:$name, shape:spatial.fromMap($shape)})",
    {"name": "Square", "shape": shape},
)
print(shape.domain, shape.srid, shape.layout, len(shape.wkb))
```

Binding `Spatial` sends a lossless envelope. Use `spatial.fromMap($shape)` to
promote it into a database spatial value. `RETURN $shape` alone echoes the map;
it does not change the server’s value type. To import external bytes or text,
use `spatial.fromWKB`, `spatial.fromWKT`, or `spatial.fromGeoJSON` with parameters.
The server performs geometry/topology validation. M/ZM, curves, surfaces and
solids are outside the current database scope. See the [spatial guide](docs/SPATIAL.md).

## Errors and connection lifecycle

Server errors raise `DatabaseError` with the server's `code`, `message` and
`metadata`. The code is split into `classification`, `category` and `title`, and
`is_client_error`, `is_transient`, `is_database_error` and `is_retryable` answer
the common questions. `is_retryable` is true for transient errors; the decision
to retry stays with your application. Published codes are constants in
`galactus.codes`:

```python
from galactus import DatabaseError, codes

try:
    driver.execute_query("CREATE (:Account {email:$email})", {"email": "ada@example.com"})
except DatabaseError as error:
    if error.code == codes.CONSTRAINT_VALIDATION_FAILED:
        print("That email is already registered")
    else:
        raise
```

After a database error the driver resets the connection and stays usable. It
discards the connection after a network, timeout, TLS or protocol failure, and
after rejected authentication; open a new driver in those cases.

| Symptom | Check |
|---|---|
| Connection refused | Host, port, listener and network reachability |
| Authentication rejected | Database username and configured password |
| Database not found | Explicit database name; omit it to use the server default |
| TLS negotiation fails | Server certificate and key, `trusted_certificates`, and the certificate host name |
| Unsupported parameter | Convert the object to a supported scalar/container or named value |
| Driver is closed after an error | The connection failed at the network, TLS or protocol level; open a new driver |

Credentials and parameters are not logged by the driver. Avoid writing them to
application logs when reporting errors. The driver performs no automatic write
retries and has no background connection pool to recover failed connections.

## Testing

Run from the repository root:

```sh
python tests/test_driver.py
```

Fixtures and tests are self-contained. Without `GDB_TEST_URI`, live database
tests are skipped. For integration tests, use a fresh disposable server and
set `GDB_TEST_URI` and `GDB_TEST_PASSWORD`; tests create data and exercise
transactions. The configured default database is used. Reset the disposable
database before repeating the suite.

See [test instructions](tests/README.md) for platform prerequisites and environment
examples. The shared live suite runs three times, on Bolt 5.4, on Bolt 4.4 and over
TLS, and covers 57 spatial cases, integer boundaries, native values, large chunked
payloads, element ids, datetimes, decimals, transactions, error recovery and
certificate trust.

## Current scope

Version 0.2 provides direct connections over Bolt 5.4 or 4.4, verified TLS,
basic authentication, parameterised queries, eager records and summaries,
explicit transactions, recovery after database errors, classified errors, native
type mapping and full supported spatial interchange. Each driver owns one
connection and runs synchronously. Pooling, routing, retry callbacks, lazy
cursors and cancellation are planned for follow-on releases. Messages are capped
at 64 MiB and nesting at 64 levels; aggregate result memory can exceed a single
message.

The driver is tested on Windows against a real Galactus server. See
[the shared blueprint](docs/BLUEPRINT.md) and the
[implementation overview](docs/OVERVIEW.md) for the precise contract.

## Feedback and contribution

Use [GitHub issues](https://github.com/galactusdb/galactus-db-python-driver/issues) for reproducible
bugs and focused feature requests. Include runtime/OS versions, driver commit,
expected behaviour and a small reproduction with credentials and sensitive
data removed. Keep changes dependency-light and run the relevant tests before
opening a pull request against `main`.

Visit [galactusdb.com](https://galactusdb.com) for Galactus DB, or browse the
[other language drivers](https://galactusdb.com/product/drivers).

## Licence

Apache License 2.0. See [LICENSE](LICENSE).
