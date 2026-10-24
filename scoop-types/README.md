# Scoop Types

This package defines all types used in API model generation. `scoop.tsp` is
compiled to OpenAPI 3.1 (`build/@typespec/openapi3/openapi.yaml`), which
`scoop-api` turns into Pydantic models with `datamodel-codegen`. The query AST
lives in `ast.tsp`, which `scoop.tsp` imports.

## Usage

```sh
pnpm install
just build          # pnpm exec tsp compile scoop.tsp
```

From the repo root, `just codegen` builds the spec and regenerates
`scoop-api/api/models.py`.
