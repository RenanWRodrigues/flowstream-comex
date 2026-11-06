# Dados sintéticos

24 meses de operação **fictícia** de um agente de cargas de Itajaí, gerados por
`flowstream synthetic generate` e carregados no schema `bronze` por
`flowstream synthetic load`. Nenhum dado é real: CNPJs têm raiz `00.000.001` a `00.000.999`
(nunca `00.000.000`, do Banco do Brasil), e armadores e companhias aéreas são inventados.

```bash
make synthetic                                   # gera (semente 42) e carrega
flowstream synthetic generate --seed 7 --months 6 --out data/teste
flowstream synthetic load --dir data/teste
```

## Garantias

| Garantia | Como |
| --- | --- |
| Mesma semente, mesmos dados | Todo sorteio sai de um único `random.Random(seed)`; o período é fixo no `config.yaml` (não depende de "hoje"); o hash dos CSVs é impresso e testado |
| Identificadores válidos | Contêineres, AWBs e CNPJs são criados com os tipos de `flowstream.domain`, que validam na construção |
| Linha do tempo coerente | Todo embarque passa em `validate_timeline` com "agora" = fim do período |
| Proporções com meta | Modal, porte, segmento, UF e cotações ganhas são distribuídos por **cota exata**, não por sorteio |
| Carga idempotente | `load` apaga e recarrega as 7 tabelas numa única transação (`TRUNCATE` + `COPY`); falha desfaz tudo e grava `ERRO` em `ops.pipeline_runs` |
| Desempenho | Geração + carga em cerca de 2 s, com pico de 78 MB de memória |

## Volumes (padrão)

| Tabela | Linhas | Grão |
| --- | --- | --- |
| `bronze.vendedores` | 8 | vendedor |
| `bronze.clientes` | 300 | cliente |
| `bronze.cotacoes` | 6.000 | cotação |
| `bronze.embarques` | 1.800 | processo (1 por cotação ganha) |
| `bronze.equipamentos` | ~1.500 | contêiner ou isotanque do processo |
| `bronze.itens_financeiros` | ~9.700 | receita ou custo, na moeda original |
| `bronze.tracking_eventos` | ~8.700 | evento de rastreamento |

## Distribuições

Todos os números ficam em `src/flowstream/synthetic/config.yaml`; mudar a configuração muda
os dados sem mexer no código.

- **Clientes:** porte pequeno 50%, médio 35%, grande 15%. O peso de cada cliente é o do
  porte (1, 4 e 25) multiplicado por uma lognormal individual, o que dá um Pareto realista:
  os 20% maiores clientes trazem ~75% dos embarques. UF: SC 70%, PR 12%, SP 10%, RS 8%.
  Dez segmentos, com destaque para têxtil, metalmecânico e alimentos.
- **Cotações:** sazonalidade mensal com pico de agosto a outubro (carga de Natal saindo da
  Ásia) e vale em dezembro e fevereiro, mais 8% de crescimento ao ano. Cotações são pedidas
  em dias úteis, das 8h às 17h; respostas e bookings caem no horário comercial (8h-18h).
  Tempo de resposta lognormal truncado em 10 dias (mediana de 6 h no aéreo e 16 h nos
  demais, em horas corridas; ~10% passam de 3 dias), e nenhuma resposta depois do corte.
  Ganham 30%, com chance maior para respostas em menos de 24 h e diferenças entre vendedores
  (22% a 38%). Das demais: perdida 55%, expirada 10% e, no último mês, em aberto.
- **Modais (embarques):** FCL 45%, LCL 25%, aéreo 18%, rodoviário 7%, isotanque 3%,
  projeto 2%. Importação 65%. Regiões: Ásia 60%, Europa 20%, América do Norte 12%,
  Mercosul 6%, Oriente Médio 2%.
- **Ano-Novo Chinês:** as fábricas param, e 60% dos embarques da Ásia que sairiam de 7 dias
  antes a 14 dias depois do feriado são empurrados para depois dele (1 a 10 dias após a
  janela), o que também cria a corrida pós-feriado.
- **Prazos:** ETA = ETD + transit time médio da rota (seed `rotas`). 80% chegam até 1 dia
  depois do ETA. O atraso dos demais depende do modal e nunca passa de 1,5× o transit
  time: marítimo com mediana de ~4 dias e cauda até 45; aéreo até ~3,5 dias; rodoviário
  até ~5,5. Pontualidade por armador de 72% a 90%; meses de pico perdem 5 pontos.
- **Carga:** FCL com 1 a 5 contêineres (70% 40'HC), com ocupação de 75% a 90% (até 30 m³
  no 20' e 68 m³ no 40'HC); LCL de 1 a 15 m³; aéreo de 50 a 3.000 kg com peso taxável
  (1 m³ = 167 kg); isotanques de 18 a 26 t.
- **Financeiro:** cada processo sorteia uma margem entre 8% e 25% (moda 15%). Frete em USD
  (EUR em 40% das rotas da Europa; BRL no rodoviário); o frete de um 20' custa de 60% a 75%
  do de um 40'HC. THC, seguro e armazenagem em BRL. Demurrage em ~8% dos FCL de
  **importação** que chegaram (na exportação, quem paga é o comprador no destino); em 30%
  desses casos o agente **absorve** o custo (sem receita correspondente), o que derruba a
  margem do processo abaixo de 8%.
  A data de competência é a do ATD (frete), do ATA (armazenagem) ou da cobrança (demurrage).
- **Tracking:** booking, gate in, embarque, transbordo (30% das rotas da Ásia), atualizações
  de ETA nos atrasados (alimentam o alerta `eta_alterado` do P13), chegada, liberação e
  **devolução do vazio** (contêineres de importação): dentro do free time, ou depois dele
  nos processos com demurrage — que é cobrada na devolução.

## Limitações conhecidas

- Valores ficam na moeda original; a conversão pela PTAX da data de competência é feita no
  dbt (P05).
- Não há histórico de mudança de vendedor ou segmento do cliente: o snapshot SCD2 do P06
  começará a registrar mudanças a partir das próximas cargas.
- Embarques cancelados não são gerados.
- Feriados não entram no gerador (só fins de semana); a camada ouro os conhece pela
  `dim_data`.
- Não há bookings nas últimas semanas antes do corte (as cotações do último mês ficam em
  aberto), nem status ENTREGUE na importação, e o ETA atualizado só atrasa.
- Proporções com cota exata deixam os números "perfeitos" (exatamente 45% de FCL etc.).
- Os meses das pontas têm menos embarques: nov/2024 porque as cotações só começam nele, e
  out/2026 porque as cotações do último mês ainda estão em aberto. Exclua-os de análises de
  tendência.
- Rotas de exportação são poucas (todo o LCL de exportação vai para Buenos Aires); ampliar
  `dbt/seeds/rotas.csv` enriquece os dados sem mudar código.

## Auditoria

O subagente `data-quality-auditor` revisou a primeira versão e apontou cinco pontos
implausíveis, todos corrigidos com teste: atraso do aéreo e das rotas curtas igual ao do
marítimo (voos chegando 45 dias depois do ETA), mesmo frete para 20' e 40'HC, demurrage em
exportação, Pareto de clientes fraco e contêineres cheios a 100% do volume. A lista de
testes dbt sugerida por ele entra no P05 e no P06.

A auditoria da camada ouro (P06) apontou mais quatro, também corrigidos com teste:
cotações e respostas em fins de semana e de madrugada, pico artificial de respostas em
exatamente 240 h (o teto cortava a distribuição), uma resposta depois do fim do período
e o risco de demurrage sem relação com a demurrage cobrada (faltava a devolução do vazio).
