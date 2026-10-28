# Changelog

## 0.2.0 (28/10/2026)

- Speaks Bolt 5.0 to 5.4 and falls back to Bolt 4.4 when the server offers only
  that. From 5.1 the driver authenticates with LOGON and sends `bolt_agent`.
- `protocol_version`, `server_agent`, `connection_id` and `last_bookmark` on the
  driver.
- After a database error the driver resets the connection, closes any open
  transaction and stays usable. Network, TLS, protocol and authentication
  failures still discard the connection.
- `DatabaseError` adds `message`, `classification`, `category`, `title`,
  `is_client_error`, `is_transient`, `is_database_error` and `is_retryable`.
  Published server codes are constants in `galactus.codes`.
- `bolt+s://` works directly against a Galactus server running TLS. The new
  `trusted_certificates` option names a PEM file to trust instead of the system
  store; it is rejected on `bolt://`.
- Nodes and relationships carry `element_id` (relationships also
  `start_element_id` and `end_element_id`), filled from the integer id on 4.4.
- Offset datetimes use tag `I` on Bolt 5 and `F` on 4.4; all four datetime tags
  decode on any version. `ZonedDateTime` gains a `basis` field (`'local'` or
  `'utc'`) with `ZonedDateTime.local(...)` and `ZonedDateTime.utc(...)`.
- `decimal.Decimal` parameters are sent as exact plain text; NaN and infinities
  are rejected.
- The user agent is `galactus-db-python-driver/0.2.0`.

Compatibility: `Node`, `Relationship`, `UnboundRelationship` and `ZonedDateTime`
have extra trailing fields, so code that unpacks them positionally needs
updating. Attribute access is unchanged. A query after a database error now
succeeds instead of raising `ConnectionError`.

## 0.1.0

- First release: Bolt 4.4, basic authentication, parameterised queries, explicit
  transactions, native type mapping and spatial values.
