---
name: python-data-engineering
description: Padrões oficiais de desenvolvimento Python do time de Engenharia de Dados — Poetry com layout src/, arquitetura modular de pipelines ETL/ELT, Ruff, Pytest com cobertura mínima de 50%, MkDocs Material, tipagem, configuração segura, logging e CI. Use ao criar, modificar, revisar ou refatorar qualquer projeto Python do time.
---

# Padrões Python — Engenharia de Dados

Este documento é a referência **obrigatória** para pessoas e agentes de IA que criam, mantêm, revisam ou refatoram projetos Python do time. Ele é curto de propósito. Os detalhes e exemplos longos ficam nos arquivos complementares.

| Arquivo | Conteúdo |
|---|---|
| [references/architecture.md](references/architecture.md) | Responsabilidade de cada camada, com um exemplo completo de pipeline |
| [references/code-patterns.md](references/code-patterns.md) | Tipagem, configuração, logging e exceções, com exemplos certos e errados |
| [references/data-engineering.md](references/data-engineering.md) | Idempotência, retries, incremental, qualidade de dados, performance e observabilidade |
| [references/testing.md](references/testing.md) | Padrões de teste, fixtures, mocks e evolução da cobertura |
| [templates/](templates/) | `pyproject.toml`, `mkdocs.yml`, CI, `.gitignore`, `.env.example` e template de PR |

Nos exemplos, **`nome_projeto`** é um placeholder: troque-o pelo nome real do pacote em todos os arquivos.

## Níveis de exigência

- **MUST**: obrigatório. Uma violação bloqueia o merge.
- **MUST NOT**: proibido. Uma violação bloqueia o merge.
- **SHOULD**: recomendado. Não seguir exige justificativa no PR.
- **MAY**: opcional, conforme o contexto.

---

## 1. Princípios

Toda implementação MUST seguir estes princípios:

- **Clean Code, SOLID, DRY, KISS e YAGNI.** Escreva o mais simples que resolve o problema de hoje.
- **Separation of Concerns, alta coesão e responsabilidade única.** Cada módulo, classe ou função tem um motivo para mudar.
- **Baixo acoplamento.** Use dependências explícitas e injetadas, e prefira composição a herança.
- **Explicit is better than implicit.** Use tipos, parâmetros e configuração declarados, sem "mágica".
- **Fail Fast.** Valide entradas e configuração cedo e falhe com erro claro, nunca em silêncio.
- **Testabilidade desde a concepção.** Lógica pura, isolada de I/O.
- **Observabilidade e reprodutibilidade.** Toda execução deve ser rastreável e repetível.
- **Simplicidade arquitetural.** MUST NOT criar abstrações, camadas ou interfaces sem um consumidor real.

## 2. Poetry: dependências e ambientes

Poetry (versão 2.0 ou superior) é a ferramenta **oficial e exclusiva** para dependências, ambientes virtuais e empacotamento.

**MUST**
- Criar e gerenciar o projeto com Poetry, usando exclusivamente o layout `src/`.
- Centralizar a configuração no `pyproject.toml` (`[project]` no padrão PEP 621, mais `[tool.*]`).
- Versionar o `poetry.lock` em projetos de aplicação.
- Separar dependências de produção (`[project.dependencies]`) das de desenvolvimento (grupo `dev`).
- Declarar `requires-python` e respeitar a compatibilidade das dependências com essa faixa.
- Manter o ambiente virtual em `.venv/` dentro do projeto (`virtualenvs.in-project`).
- Executar ferramentas e a aplicação com `poetry run`.

**MUST NOT**
- Instalar pacotes com `pip`, `pip install -r requirements.txt` ou `python -m pip`.
- Gerenciar dependências em paralelo com Conda, Pipenv ou uv.
- Alterar o `.venv` manualmente ou versioná-lo.
- Editar dependências no `pyproject.toml` sem regenerar o lock. Toda mudança passa por `poetry add`, `poetry remove` ou `poetry lock`.

**Comandos oficiais**

```bash
# Instalar o Poetry (uma vez por máquina, fora de qualquer projeto)
pipx install poetry                      # ou o instalador oficial: https://python-poetry.org/docs/#installation

# Criar um projeto (Poetry >= 2.0 já gera o layout src/)
poetry new nome_projeto && cd nome_projeto
poetry init                              # para um diretório já existente

# Ambiente
poetry config virtualenvs.in-project true --local   # cria poetry.toml (versionável)
poetry env use python3.12                # escolhe o interpretador
poetry env info                          # inspeciona o ambiente atual
poetry env remove --all                  # recria do zero (depois rode poetry install)

# Dependências
poetry add <pacote>                      # produção
poetry add --group dev <pacote>          # desenvolvimento
poetry remove <pacote>
poetry update <pacote>                   # atualiza respeitando as restrições
poetry show --outdated                   # lista as desatualizadas
poetry lock                              # regenera o lock após mudar restrições
poetry check --lock                      # valida pyproject.toml e a consistência do lock

# Instalação reproduzível
poetry install                           # produção + dev, a partir do lock
poetry install --only main               # só produção (imagens e deploy)
poetry sync                              # instala e remove pacotes fora do lock

# Execução
poetry run nome_projeto                  # entry point definido em [project.scripts]
poetry run pytest
poetry build                             # gera sdist/wheel em dist/
```

Veja um `pyproject.toml` completo em [templates/pyproject.toml](templates/pyproject.toml).

## 3. Arquitetura e organização modular

A estrutura abaixo é uma **referência**. Crie só os módulos de que o projeto precisa e MUST NOT criar diretórios vazios.

```text
nome_projeto/
├── pyproject.toml / poetry.lock / poetry.toml
├── README.md / .gitignore / .env.example / mkdocs.yml
├── src/nome_projeto/
│   ├── __init__.py
│   ├── main.py            # composition root e CLI; sem regra de negócio
│   ├── config/            # Settings validados na inicialização
│   ├── domain/            # entidades e regras de negócio puras
│   ├── schemas/           # contratos de entrada e saída (validação)
│   ├── models/            # modelos de persistência (ORM, tabelas)
│   ├── extractors/        # leitura de fontes (APIs, arquivos, bancos)
│   ├── transformers/      # transformações puras, sem I/O
│   ├── loaders/           # escrita em destinos
│   ├── repositories/      # acesso aos dados que a própria aplicação mantém
│   ├── services/          # casos de uso que orquestram domain e repositories
│   ├── pipelines/         # composição extract → transform → load
│   ├── exceptions/        # hierarquia de exceções do projeto
│   └── utils/             # só utilidades genuinamente genéricas
├── tests/{unit,integration}/ + conftest.py
├── docs/{index,architecture,getting-started,development}.md
└── .github/workflows/ci.yml
```

**MUST**
- Separar regra de negócio (`domain`, `transformers`) de I/O e infraestrutura (`extractors`, `loaders`, `repositories`).
- Manter extract, transform e load em componentes distintos, nunca numa função monolítica.
- Receber as dependências por parâmetro (injeção explícita) e montá-las em `main.py`.
- Garantir que cada componente seja testável isoladamente.

**MUST NOT**
- Pôr lógica de negócio em `main.py`.
- Criar dependências circulares. A direção permitida é `pipelines → extractors/transformers/loaders → domain/schemas`, e `domain` não importa nada de infraestrutura.
- Usar `utils/` como depósito de código sem lugar.
- Executar código com efeito colateral (conexões, leituras, pipelines) na importação de um módulo.

**SHOULD**
- Funções com até cerca de 40 linhas e módulos com até cerca de 400 linhas. Acima disso, avalie dividir.
- Usar `Protocol` para contratos de I/O quando houver mais de uma implementação ou para isolar testes.

Responsabilidades e exemplo completo: [references/architecture.md](references/architecture.md).

## 4. Qualidade de código: Ruff

Ruff é a ferramenta **oficial e única** de lint, formatação e organização de imports. MUST NOT usar Black, Flake8, autopep8 ou isort em paralelo.

- Configuração no `pyproject.toml`. Famílias obrigatórias: `E`, `F`, `I`, `B`, `UP`, `SIM`, `C4`. O template adiciona `PTH` (pathlib), `T20` (proíbe `print`) e `RUF`.
- A ordenação de imports é feita pelo **lint** (regra `I`, via `--fix`). O `ruff format` sozinho não ordena imports.
- MUST NOT desabilitar regras globalmente sem justificativa no PR. Supressões pontuais usam `# noqa: <CÓDIGO>` específico, nunca um `# noqa` genérico.

```bash
poetry run ruff check .            # lint
poetry run ruff check . --fix      # corrige o que for seguro, inclusive imports
poetry run ruff format .           # formata
poetry run ruff format --check .   # verifica sem alterar (usado no CI)
```

Nenhum código está pronto com erro de lint ou de formatação.

## 5. Testes: Pytest

Pytest é o framework **exclusivo**, e a cobertura é medida com `pytest-cov`.

**MUST**
- Cobertura global mínima de **50%**, aplicada por `--cov-fail-under=50` e por `fail_under` no `pyproject.toml`. Esse é o piso, não a meta.
- Separar `tests/unit/` (sem rede, banco ou disco compartilhado) de `tests/integration/` (marcados com `@pytest.mark.integration`).
- Testes determinísticos: sem dependência de horário, ordem, rede ou aleatoriedade sem seed.
- Mocks e stubs para dependências externas em testes unitários.
- Cobrir caminho feliz, exceções e casos de borda (vazio, nulo, duplicado, schema inválido).
- Priorizar transformações, validações, regras de negócio e funções críticas.

**MUST NOT**
- Escrever testes que só espelham a implementação, sem verificar comportamento.
- Reduzir `fail_under`, ou excluir arquivos da cobertura, para aprovar uma mudança.

```bash
poetry run pytest tests/ \
  --cov=nome_projeto \
  --cov-report=term-missing \
  --cov-report=xml \
  --cov-fail-under=50

poetry run pytest -m "not integration"   # só os unitários
```

**Quando criar ou atualizar testes (MUST)**
- Função ou comportamento novo: pelo menos um teste do caminho feliz e um de falha ou borda.
- Correção de bug: um teste de regressão que falha antes da correção.
- Mudança de contrato (schema, assinatura pública): atualizar os testes afetados no mesmo PR.
- Refatoração sem mudança de comportamento: os testes existentes passam sem alteração.

**Evolução da cobertura (SHOULD)**: o código novo ou alterado no PR deve ter 80% ou mais de cobertura. Módulos `domain/` e `transformers/` devem buscar 80% ou mais. Quando a cobertura global passar do `fail_under` atual com folga de 10 pontos, suba o `fail_under` (catraca: ele nunca desce). Detalhes em [references/testing.md](references/testing.md).

## 6. Documentação: MkDocs Material

**MUST**
- `README.md` como porta de entrada: o que é, como instalar, como rodar e o link para a documentação.
- `docs/index.md` como página inicial, mais `architecture.md`, `getting-started.md` e `development.md`.
- Documentar variáveis de ambiente (nome, obrigatoriedade, default e exemplo), pipelines e seus fluxos, contratos de entrada e saída, e troubleshooting.
- Docstrings no **Google Style** em módulos, classes e funções públicas.
- `mkdocs build --strict` sem warnings.
- Atualizar a documentação no mesmo PR que muda uma interface pública ou um comportamento.

**SHOULD**
- Usar `mkdocstrings[python]` para gerar a referência de API a partir das docstrings.
- Registrar decisões arquiteturais relevantes em `docs/adr/NNNN-titulo.md` (contexto, decisão, consequências).
- Manter um `CHANGELOG.md` quando o projeto tiver consumidores externos.

```bash
poetry add --group dev mkdocs-material "mkdocstrings[python]"
poetry run mkdocs serve           # local, em http://127.0.0.1:8000
poetry run mkdocs build --strict  # validação (CI)
```

Configuração inicial em [templates/mkdocs.yml](templates/mkdocs.yml).

## 7. Type hints e contratos

- MUST: tipar parâmetros e o retorno de toda função ou método público, inclusive `-> None`.
- MUST: usar a sintaxe moderna compatível com `requires-python`, como `list[str]`, `X | None` e `collections.abc.Iterable`.
- MUST: usar `pathlib.Path` para caminhos, nunca `os.path` com strings.
- MUST NOT: usar `Any` sem justificativa. Prefira `object`, `TypeVar`, `Protocol` ou um tipo concreto.
- SHOULD: escolher a estrutura conforme a necessidade. `dataclass(frozen=True, slots=True)` para valores internos; `TypedDict` para dicts com formato fixo; `Protocol` para contratos de comportamento; Pydantic para validar dados externos.
- SHOULD: verificar tipos com **mypy** (`strict` em `src/`), rodando no CI. Ao adotar o mypy, ele passa a ser obrigatório.

Exemplos em [references/code-patterns.md](references/code-patterns.md#tipagem).

## 8. Configuração e segurança

**MUST**
- Separar configuração de código. Parâmetros externos vêm de variáveis de ambiente.
- Validar a configuração obrigatória na inicialização (recomendado: `pydantic-settings`) e falhar antes de processar dados.
- Manter um `.env.example` com todas as variáveis e valores fictícios.
- Usar consultas SQL parametrizadas.
- Aplicar o menor privilégio a credenciais de banco, buckets e APIs.

**MUST NOT**
- Versionar `.env` com valores reais.
- Escrever senhas, tokens ou chaves no código, em testes, notebooks ou documentação.
- Registrar credenciais ou dados pessoais (PII) em logs. Use `SecretStr` e mascaramento.
- Montar SQL com f-string ou concatenação de entrada externa.

**SHOULD**
- Usar um gerenciador de segredos em produção (por exemplo AWS Secrets Manager, GCP Secret Manager, Azure Key Vault ou Vault).
- Rodar `pip-audit` no CI para checar vulnerabilidades das dependências. Ele é um auditor, não um instalador, e roda via `poetry run`.

## 9. Logging e exceções

**MUST**
- Usar o módulo `logging` com um logger por módulo: `logger = logging.getLogger(__name__)`. A configuração é feita uma vez, em `main.py`.
- Usar níveis coerentes: `DEBUG` para diagnóstico, `INFO` para marcos da execução, `WARNING` para o que é anômalo mas tratado, `ERROR` para falha de operação e `CRITICAL` para a aplicação inoperante.
- Incluir contexto nos logs (`run_id`, pipeline, partição, volumes) e passar argumentos com `%s` (lazy), não com f-string.
- Criar uma hierarquia própria de exceções em `exceptions/` e capturar exceções **específicas**.
- Preservar a causa original com `raise NovaExcecao(...) from exc`.
- Liberar recursos com context managers (`with`).

**MUST NOT**
- Usar `print()` como log em código de aplicação (a regra `T20` do Ruff bloqueia).
- Escrever `except:` ou `except Exception:` que engole o erro. Capturar `Exception` só é aceito na borda (`main.py`), para logar com `logger.exception` e encerrar com código diferente de zero.
- Permitir falhas silenciosas, como `pass` em `except` ou retornar `None` para sinalizar erro.

```python
# ❌ Errado
try:
    rows = extractor.extract()
except Exception:
    print("erro")
    rows = []

# ✅ Certo
try:
    rows = extractor.extract()
except requests.RequestException as exc:
    raise ExtractionError(f"Falha ao extrair de {source}") from exc
```

Mais exemplos (configuração de logging, `run_id`, context managers): [references/code-patterns.md](references/code-patterns.md#logging).

## 10. Engenharia de dados

Estas regras valem para Pandas, Polars, PyArrow, SQLAlchemy ou PySpark. MUST NOT adicionar uma dessas bibliotecas só para seguir um padrão.

**Pipelines (ETL/ELT)**
- MUST: separar extract, transform e load, com transformações puras.
- MUST: tornar a execução **idempotente**, de modo que rodar duas vezes a mesma partição produza o mesmo resultado (overwrite de partição, upsert por chave ou staging com troca).
- MUST: parametrizar fonte, destino e período (`--start-date`, `--end-date`), sem datas ou caminhos fixos no código.
- MUST: expor um entry point claro para orquestradores (função `run(...)` ou CLI) e nunca executar na importação.
- MUST: fazer retries só em erros transitórios, com limite de tentativas e backoff exponencial.
- SHOULD: processar de forma incremental (watermark ou partição) quando o volume justificar.

**Qualidade e contratos de dados**
- MUST: validar o schema na entrada e antes da carga: colunas, tipos, nulidade e unicidade de chaves.
- MUST: tratar mudança de schema explicitamente, falhando ou registrando, nunca absorvendo em silêncio.
- MUST: isolar registros inválidos (quarentena ou dead-letter) com o motivo e o `run_id`, em vez de descartá-los.
- SHOULD: formalizar contratos de dados entre produtores e consumidores em `schemas/`.

**Performance**
- SHOULD: preferir operações vetorizadas. MUST NOT usar `iterrows`/`apply` linha a linha onde existe alternativa vetorizada.
- SHOULD: ler só as colunas e partições necessárias, processar em lotes ou em streaming quando o volume não couber em memória, e evitar leituras e escritas redundantes.
- MUST NOT: introduzir paralelismo ou concorrência sem uma medição que comprove a necessidade.

**Observabilidade**
- MUST: registrar o início, o fim, a duração e o status de cada execução e etapa.
- MUST: registrar volumes (lidos, válidos, inválidos, gravados) e falhas.
- SHOULD: separar métricas técnicas (duração, retries) de métricas de qualidade (taxa de nulos, rejeitados), e permitir reprocessar uma partição específica.

Padrões e código: [references/data-engineering.md](references/data-engineering.md).

## 11. Git e revisão de código

- MUST: seguir **Conventional Commits**, como `feat(extractors): adiciona extração incremental de laps` ou `fix: corrige timezone em sessions`. Tipos: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`, `perf`, `build`.
- MUST: manter PRs pequenos e com um objetivo só (SHOULD: até cerca de 400 linhas alteradas, sem contar o lock), incluindo testes e documentação atualizados.
- MUST: exigir revisão de outra pessoa para mudanças arquiteturais, de contratos de dados ou de CI.
- MUST NOT: commitar credenciais, `.env`, `.venv/`, caches, artefatos de build (`dist/`, `site/`), relatórios de cobertura ou dados locais.
- MUST: usar um `.gitignore` do ecossistema Python ([templates/gitignore](templates/gitignore)) e o template de PR ([templates/pull_request_template.md](templates/pull_request_template.md)).

## 12. Integração contínua

O CI MUST falhar se qualquer etapa obrigatória falhar. A ordem é:

1. Instalar o Poetry (via pipx) e o Python.
2. `poetry check --lock`, que valida o projeto e a consistência do lock.
3. `poetry install`.
4. `ruff check`.
5. `ruff format --check`.
6. `mypy`, quando configurado.
7. `pytest` com `--cov-fail-under=50`.
8. `mkdocs build --strict`.
9. `pip-audit`, quando configurado.

Workflow pronto: [templates/ci.yml](templates/ci.yml), copiado para `.github/workflows/ci.yml`.

## 13. Regras para agentes de IA

Ao criar ou modificar um projeto Python, o agente MUST:

1. Ler este `SKILL.md`, e as referências pertinentes à tarefa, antes de propor alterações.
2. Inspecionar a estrutura, o `pyproject.toml` e as convenções existentes antes de escrever código.
3. Respeitar a arquitetura do repositório e reutilizar componentes existentes.
4. Não adicionar bibliotecas sem justificar a necessidade. Se for adicionar, usar `poetry add`.
5. **Nunca usar `pip`**, em nenhuma circunstância.
6. Não criar arquivos, camadas ou abstrações desnecessárias.
7. Escrever código modular, tipado e com docstrings nas interfaces públicas.
8. Criar ou atualizar os testes das funcionalidades alteradas.
9. Atualizar a documentação afetada.
10. Executar `ruff check`, `ruff format --check` e `pytest` com cobertura (mais `mypy` e `mkdocs build --strict`, se configurados) antes de considerar a tarefa concluída.
11. **Não declarar uma verificação como aprovada sem tê-la executado.** Reportar falhas com a saída real.
12. Não reduzir `fail_under`, não adicionar exclusões de cobertura e não desabilitar regras para "fazer passar".
13. Preservar a compatibilidade das interfaces públicas, salvo pedido explícito.
14. Encerrar com um resumo das alterações e das validações executadas, com os resultados.

Em conflito entre rapidez e conformidade, priorize correção, segurança, manutenção e simplicidade, nessa ordem.

## 14. Definition of Done

- [ ] A estrutura e a arquitetura do projeto foram respeitadas.
- [ ] As dependências foram gerenciadas só pelo Poetry, e `poetry check --lock` passa.
- [ ] `poetry run ruff check .` passa sem erros, com os imports organizados.
- [ ] `poetry run ruff format --check .` passa.
- [ ] Os testes passam e a cobertura global é de 50% ou mais.
- [ ] As interfaces públicas estão tipadas, e o mypy passa, se configurado.
- [ ] A documentação afetada foi atualizada e `mkdocs build --strict` passa.
- [ ] Não há credenciais nem dados sensíveis expostos, no código ou nos logs.
- [ ] Não há código morto nem duplicação injustificada.
- [ ] O projeto instala e executa de forma reproduzível (`poetry install` e `poetry run nome_projeto`).
