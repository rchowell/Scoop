namespace Scoop;

// ============================================================================
// Query
// ============================================================================

@doc("A SELECT query: a minimal, pareto subset of ANSI SQL")
model Query {
  @doc("SELECT DISTINCT")
  distinct?: boolean = false;

  @doc("Projected expressions, in output order")
  select: SelectItem[];

  @doc("Row source; omitted for e.g. SELECT 1")
  from?: FromItem;

  @doc("Row filter applied before grouping")
  where?: Expr;

  @doc("Grouping expressions")
  group_by?: Expr[];

  @doc("Group filter applied after grouping")
  having?: Expr;

  @doc("Sort keys, most significant first")
  order_by?: OrderItem[];

  @doc("Maximum rows to return")
  @minValue(0)
  limit?: int64;

  @doc("Rows to skip before returning results")
  @minValue(0)
  offset?: int64;
}

@doc("One projected expression, e.g. count(*) AS n")
model SelectItem {
  expr: Expr;

  @doc("Output column name (AS alias)")
  `alias`?: string;
}

@doc("Sort direction")
enum SortDirection {
  Asc: "asc",
  Desc: "desc",
}

@doc("Where nulls sort relative to non-null values")
enum NullsOrder {
  First: "first",
  Last: "last",
}

@doc("One ORDER BY key")
model OrderItem {
  expr: Expr;

  @doc("Defaults to the backend's default (ascending)")
  direction?: SortDirection;

  @doc("Defaults to the backend's default")
  nulls?: NullsOrder;
}

// ============================================================================
// From
// ============================================================================

@doc("A named table or view")
model TableRef {
  kind: "table";

  @doc("Table identifier, optionally qualified (e.g. [\"main\", \"users\"])")
  path: string[];

  `alias`?: string;
}

@doc("Join type")
enum JoinType {
  Inner: "inner",
  Left: "left",
  Right: "right",
  Full: "full",
  Cross: "cross",
}

@doc("A join of two row sources")
model Join {
  kind: "join";
  join_type: JoinType;
  left: FromItem;
  right: FromItem;

  @doc("Join condition; omitted for cross joins")
  on?: Expr;
}

@doc("A subquery in FROM, e.g. (SELECT ...) AS t")
model DerivedTable {
  kind: "subquery";
  query: Query;
  `alias`: string;
}

@doc("A row source in FROM")
@discriminated(#{ envelope: "none", discriminatorPropertyName: "kind" })
union FromItem {
  table: TableRef,
  join: Join,
  subquery: DerivedTable,
}

// ============================================================================
// Expressions
// ============================================================================

@doc("Binary operator")
enum BinaryOp {
  Add: "add",
  Sub: "sub",
  Mul: "mul",
  Div: "div",
  Mod: "mod",
  Concat: "concat",
  Eq: "eq",
  Ne: "ne",
  Lt: "lt",
  Le: "le",
  Gt: "gt",
  Ge: "ge",
  And: "and",
  Or: "or",
}

@doc("Unary operator")
enum UnaryOp {
  Neg: "neg",
  Not: "not",
}

@doc("A constant value")
model LiteralExpr {
  kind: "literal";

  @doc("The constant; null for SQL NULL. Dates and timestamps use cast")
  value: string | int64 | float64 | boolean | null;
}

@doc("A reference to a column")
model ColumnExpr {
  kind: "column";

  @doc("Column identifier, optionally qualified (e.g. [\"t\", \"id\"])")
  path: string[];
}

@doc("All columns: *, t.*, or the argument of count(*)")
model StarExpr {
  kind: "star";

  @doc("Table qualifier for t.*; omitted for a bare *")
  qualifier?: string[];
}

@doc("A unary operation, e.g. -x or NOT x")
model UnaryExpr {
  kind: "unary";
  `op`: UnaryOp;
  operand: Expr;
}

@doc("A binary operation, e.g. a + b or a AND b")
model BinaryExpr {
  kind: "binary";
  `op`: BinaryOp;
  left: Expr;
  right: Expr;
}

@doc("x IS [NOT] NULL")
model IsNullExpr {
  kind: "is_null";
  expr: Expr;
  negated?: boolean = false;
}

@doc("x [NOT] IN (a, b, ...)")
model InListExpr {
  kind: "in_list";
  expr: Expr;
  list: Expr[];
  negated?: boolean = false;
}

@doc("x [NOT] BETWEEN low AND high")
model BetweenExpr {
  kind: "between";
  expr: Expr;
  low: Expr;
  high: Expr;
  negated?: boolean = false;
}

@doc("x [NOT] LIKE pattern")
model LikeExpr {
  kind: "like";
  expr: Expr;
  pattern: Expr;
  negated?: boolean = false;
}

@doc("One WHEN ... THEN ... branch of a CASE")
model WhenClause {
  @doc("Condition (searched CASE) or value compared to the operand (simple CASE)")
  when: Expr;

  then: Expr;
}

@doc("CASE [operand] WHEN ... THEN ... [ELSE ...] END")
model CaseExpr {
  kind: "case";

  @doc("Present for a simple CASE; omitted for a searched CASE")
  operand?: Expr;

  @minItems(1)
  whens: WhenClause[];

  @doc("Result when no branch matches; NULL when omitted")
  `else`?: Expr;
}

@doc("CAST(x AS type)")
model CastExpr {
  kind: "cast";
  expr: Expr;

  @doc("Backend-native type name, e.g. \"date\" or \"varchar(10)\"")
  type: string;
}

@doc("A function call, e.g. coalesce(a, b), nullif(a, b) or count(DISTINCT x)")
model CallExpr {
  kind: "call";

  @doc("Function name")
  name: string;

  @doc("Arguments in call order")
  args: Expr[];

  @doc("Aggregate over distinct argument values, e.g. count(DISTINCT x)")
  distinct?: boolean = false;
}

@doc("An expression node")
@discriminated(#{ envelope: "none", discriminatorPropertyName: "kind" })
union Expr {
  literal: LiteralExpr,
  column: ColumnExpr,
  star: StarExpr,
  unary: UnaryExpr,
  binary: BinaryExpr,
  is_null: IsNullExpr,
  in_list: InListExpr,
  between: BetweenExpr,
  like: LikeExpr,
  case: CaseExpr,
  cast: CastExpr,
  call: CallExpr,
}
