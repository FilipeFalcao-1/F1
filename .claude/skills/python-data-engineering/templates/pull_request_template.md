<!-- Copiar para .github/pull_request_template.md -->

## O que muda

<!-- Resumo objetivo da mudança e da motivação. Link para issue/ticket. -->

## Tipo

- [ ] feat
- [ ] fix
- [ ] refactor
- [ ] test
- [ ] docs
- [ ] chore/ci/build

## Como validar

<!-- Comandos e cenários para o revisor reproduzir. -->

## Checklist (Definition of Done)

- [ ] Respeita a estrutura e a arquitetura do projeto (sem lógica em `main.py`, extract/transform/load separados).
- [ ] Dependências gerenciadas só pelo Poetry; `poetry check --lock` passa; o lock foi atualizado se houve mudança.
- [ ] `poetry run ruff check .` sem erros (imports organizados).
- [ ] `poetry run ruff format --check .` sem alterações pendentes.
- [ ] `poetry run pytest --cov=nome_projeto --cov-fail-under=50` passa.
- [ ] Testes criados ou atualizados para o comportamento alterado (inclui casos de erro e borda).
- [ ] Interfaces públicas tipadas; `poetry run mypy` passa (se configurado).
- [ ] Documentação afetada atualizada; `poetry run mkdocs build --strict` passa.
- [ ] Nenhuma credencial, `.env`, dado sensível ou artefato gerado no diff, nem em logs.
- [ ] Sem código morto ou duplicação injustificada.
- [ ] Compatibilidade de interfaces públicas preservada (ou a quebra está descrita abaixo).

## Impactos

<!-- Mudança de schema/contrato de dados, necessidade de reprocessamento, novas variáveis de ambiente, quebra de compatibilidade. Escreva "Nenhum" se não houver. -->
