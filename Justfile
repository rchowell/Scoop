mod scoop-api
mod scoop-app
mod scoop-types

default:
    @just --list

setup:
    cd scoop-types && pnpm install
    cd scoop-api && uv sync
    cd scoop-app && pnpm install

# (Re)start the Postgres + MySQL test container on localhost:15432 / localhost:13306
docker:
    -docker rm -f scoop-db
    docker run -d --name scoop-db -p 15432:5432 -p 13306:3306 \
        --health-cmd 'pg_isready -q -h /tmp -U postgres && test -S /run/mysqld/mysqld.sock' \
        goldenbeers/golden-query-challenge:1.0

codegen:
    just scoop-types build
    just scoop-api codegen
    just scoop-app codegen
