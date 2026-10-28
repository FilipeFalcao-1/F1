# Dashboard

App Streamlit que lê os marts `gold_*` do `data/f1.duckdb`, em modo somente leitura. É um extra opcional, porque a ingestão não precisa dele:

```bash
poetry install --extras dashboard
poetry run f1 dashboard        # http://localhost:8501
```

O dashboard usa o `F1_DATA_DIR` como a CLI. Antes, rode ao menos `f1 run --year Y` (ou `ingest` + `refine` + `marts build`). Sem catálogo ou sem marts, ele mostra o comando que falta.

A temporada e a corrida são escolhidas na barra lateral e valem para todas as páginas.

| Página | Conteúdo | Fonte |
|---|---|---|
| Resultado | Vencedor, pole e maior ganho; posições ganhas da largada à chegada; tabela do resultado | `gold_race_results` |
| Ritmo e pneus | Estratégia de pneus (stints por piloto); tempo de volta de até 3 pilotos; resumo por stint com degradação | `gold_stint_summary`, `gold_lap_pace` |
| Pit stops | Mediana do tempo no pit lane e do tempo parado por equipe; paradas mais rápidas | `gold_pit_stops` |
| Campeonato | Pontos acumulados após cada corrida, com até 3 competidores em destaque; classificação atual | `gold_championship_progression` |

## Decisões de visualização

- **Cores validadas**: as séries usam as três primeiras cores da paleta de referência, que passam nas checagens de daltonismo em todos os pares, nos modos claro e escuro. O dashboard segue o tema do Streamlit.
- **A cor segue a entidade**: tirar um piloto da seleção não repinta os outros (`assign_slots`).
- **Posições ganhas** usam o par divergente azul (ganhou) e vermelho (perdeu), com cinza para quem manteve a posição.
- **Compostos** seguem a convenção da F1 (macio vermelho, médio amarelo, duro cinza, intermediário verde, chuva azul). Como vermelho e verde ficam perto do limite de separação para daltonismo, cada stint também traz a letra do composto (S/M/H/I/W).
- **Ênfase no campeonato**: os competidores em destaque ganham cor, e os demais ficam em cinza como contexto.
- **Ritmo**: só voltas limpas (sem volta 1, sem entrada ou saída do pit) e até 107% da mediana da sessão, para que voltas atrás do safety car não achatem a comparação.
- Todo gráfico tem tooltip, e os números completos ficam nas tabelas abaixo dele.

## Limitações

- O grid de largada depende da classificação do mesmo fim de semana. Sem ela, a página de resultado avisa e não mostra o gráfico de posições ganhas.
- A OpenF1 só publica o tempo parado (`stop_duration`) em parte das corridas a partir do GP dos EUA de 2024. Sem ele, a página mostra só o tempo no pit lane.
- O campeonato vem de endpoints beta da OpenF1.
