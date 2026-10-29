# Desenvolvimento

## Ambiente

```bash
poetry config virtualenvs.in-project true --local
poetry install --all-extras   # inclui o extra dashboard, exigido pelos testes
```

Dependências são gerenciadas só pelo Poetry (`poetry add`, `poetry add --group dev`). Nunca use `pip`.

## Pre-commit

```bash
poetry run pre-commit install   # instala os hooks de pre-commit e pre-push (uma vez por clone)
poetry run pre-commit run --all-files
```

| Momento | Hooks |
|---|---|
| `git commit` | Higiene de arquivos (espaços, fim de linha, YAML/TOML, conflitos, arquivos > 500 KB, chaves privadas), `poetry check --lock`, `ruff check --fix`, `ruff format` e `mypy` |
| `git push` | `pytest` com cobertura mínima de 85% |

Os hooks locais usam `poetry run`, então rodam as mesmas versões do `poetry.lock` usadas no CI. Quando o Ruff corrige um arquivo, o commit é interrompido: revise a correção, faça `git add` e commite de novo.

## Definition of Done

```bash
poetry check --lock
poetry run ruff check . && poetry run ruff format --check .
poetry run mypy
poetry run pytest tests/ --cov=f1 --cov-report=term-missing --cov-fail-under=85
poetry run task docs-build      # mkdocs build --strict
```

O CI (`.github/workflows/ci.yml`) roda essa sequência e também o `pip-audit`.

## Testes

| Pasta | Marker | O que cobre |
|---|---|---|
| `tests/unit/` | — | Transformers com DataFrames pequenos (arrays da classificação, `+1 LAP`, duplicados, nulos na chave, coluna inesperada), cliente HTTP com `httpx.MockTransport`, registro de endpoints, seleção de sessões e pipelines com o lake em `tmp_path` e DuckDB em memória |
| `tests/integration/` | `integration` | Ponta a ponta sem rede: fixtures reais → bronze → silver → gold, incluindo a reexecução idempotente |
| `tests/live/` | `live` | Smoke test contra a API real. Excluído por padrão |

```bash
poetry run pytest -m "not integration"   # só unitários
poetry run pytest -m integration         # ponta a ponta
poetry run pytest -m live                # API real (manual)
```

A API falsa (`FakeOpenF1`, em `tests/conftest.py`) filtra os registros de `tests/fixtures/openf1/*.json` pelos parâmetros da query e responde 404 `No results found.` quando nada casa, como a API real. As fixtures são amostras reais pequenas da corrida 9165 e da classificação 9161 (GP de Singapura 2023) para os pilotos 1, 4 e 55.

## Como estender

### Novo campo na API

1. Acrescente a coluna em `_RAW` (e, se mudar o tipo na silver, em `_SILVER`) em `src/f1/schemas/silver.py`.
2. Se ela puder faltar, inclua-a em `_OPTIONAL`.
3. Atualize as fixtures ou os testes afetados e rode `f1 refine` para reprocessar o bronze.

### Novo mart

1. Crie `src/f1/sql/gold/gold_<nome>.sql` com um `SELECT` sobre as views `silver_*` (ou outros marts).
2. Acrescente o nome em `GOLD_MARTS` (`src/f1/pipelines/marts.py`), respeitando as dependências.
3. Cubra o mart no teste de integração.

## Convenções

- Conventional Commits (`feat(extractors): …`, `fix: …`) e PRs pequenos com o template de `.github/pull_request_template.md`.
- Logs com `%s` (lazy) e contexto (`endpoint`, `partition`, `rows`, `duration_s`). O `run_id` é injetado em todas as linhas.
- Transformers não fazem I/O, e o `main.py` não tem regra de negócio.

## Documentação

A documentação usa MkDocs Material, com a referência da API gerada pelo `mkdocstrings` a partir das docstrings (Google Style). Os atalhos ficam em `[tool.taskipy.tasks]` no `pyproject.toml`:

```bash
poetry run task docs         # serve com hot reload em http://127.0.0.1:8000
poetry run task docs-build   # mkdocs build --strict (o mesmo que o CI roda)
poetry run task --list       # lista os atalhos disponíveis
```
