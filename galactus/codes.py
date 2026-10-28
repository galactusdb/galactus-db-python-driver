"""Published Galactus server error codes. Compare ``DatabaseError.code`` against these.

Codes the server adds later still arrive as plain strings.
"""

CONSTRAINT_VALIDATION_FAILED = 'Galactus.ClientError.Schema.ConstraintValidationFailed'
TYPE_ERROR = 'Galactus.ClientError.Statement.TypeError'
ARGUMENT_ERROR = 'Galactus.ClientError.Statement.ArgumentError'
SQL_TOO_MANY_ROWS = 'Galactus.ClientError.Statement.SqlTooManyRows'
SQL_CAST_FAILED = 'Galactus.ClientError.Statement.SqlCastFailed'
TABLE_TOO_LARGE = 'Galactus.ClientError.Statement.TableTooLarge'
UNSUPPORTED_FEATURE = 'Galactus.DatabaseError.Storage.UnsupportedFeature'
PROCEDURE_NOT_FOUND = 'Galactus.ClientError.Procedure.ProcedureNotFound'
LICENSE_RESTRICTED = 'Galactus.ClientError.License.Restricted'
READ_ONLY_REPLICA = 'Galactus.ClientError.Database.ReadOnlyReplica'
TRANSACTION_TIMED_OUT = 'Galactus.ClientError.Transaction.TimedOut'
TRANSACTION_TERMINATED = 'Galactus.ClientError.Transaction.Terminated'
SNAPSHOT_TOO_OLD = 'Galactus.TransientError.Transaction.SnapshotTooOld'
FORBIDDEN = 'Galactus.ClientError.Security.Forbidden'
SYNTAX_ERROR = 'Neo.ClientError.Statement.SyntaxError'
SEMANTIC_ERROR = 'Neo.ClientError.Statement.SemanticError'
UNAUTHORIZED = 'Neo.ClientError.Security.Unauthorized'
DATABASE_NOT_FOUND = 'Neo.ClientError.Database.DatabaseNotFound'
